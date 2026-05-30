"""EcoFlow MQTT transport: keeps a connection open and decodes PV heartbeats."""
import logging
import secrets
import ssl
import threading
import time

import certifi
import paho.mqtt.client as mqtt

from ..client import (
    GET_QUOTA_INTERVAL,
    EcoflowAuthError,
    build_get_quota_request,
    decode_pv_power,
    get_mqtt_certification,
    login,
)

logger = logging.getLogger(__name__)


class EcoflowMqttListener:
    """Background thread keeping an MQTT connection open, decoding PV power.

    On each heartbeat it calls on_power(pv_watts) with the reported total PV
    power. Re-logins and reconnects automatically on failure.
    """

    def __init__(self, email: str, password: str, device_sn: str, host: str, on_power):
        self._email = email
        self._password = password
        self._sn = device_sn
        self._host = host
        self._on_power = on_power
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="ecoflow-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except EcoflowAuthError as exc:
                logger.critical("EcoFlow auth error: %s", exc)
                self._stop.wait(300)
            except Exception as exc:
                logger.warning("EcoFlow MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        token, user_id = login(self._email, self._password, self._host)
        cert = get_mqtt_certification(token, self._host)
        client_id = f"ANDROID_{secrets.token_hex(16).upper()}_{user_id}"

        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        client.username_pw_set(cert["user"], cert["password"])
        client.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(False)

        topics = [
            f"/app/device/property/{self._sn}",
            f"/app/{user_id}/{self._sn}/thing/property/get",
            f"/app/{user_id}/{self._sn}/thing/property/get_reply",
            f"/app/{user_id}/{self._sn}/thing/property/set",
            f"/app/{user_id}/{self._sn}/thing/property/set_reply",
        ]

        get_topic = f"/app/{user_id}/{self._sn}/thing/property/get"

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("EcoFlow MQTT connect failed: %s", reason_code)
                return
            for t in topics:
                c.subscribe(t, qos=1)
            c.publish(get_topic, build_get_quota_request(self._sn), qos=1)
            logger.info("EcoFlow MQTT connected, subscribed to %d topics", len(topics))

        def on_message(c, userdata, msg):
            pv_watts = decode_pv_power(msg.payload)
            if pv_watts is not None:
                try:
                    self._on_power(pv_watts)
                except Exception:
                    logger.exception("on_power callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(cert["url"], cert["port"], keepalive=15)

        last_poll = time.monotonic()
        while not self._stop.is_set():
            client.loop(timeout=1.0)
            if time.monotonic() - last_poll >= GET_QUOTA_INTERVAL:
                client.publish(get_topic, build_get_quota_request(self._sn), qos=1)
                last_poll = time.monotonic()
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
