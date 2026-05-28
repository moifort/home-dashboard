"""EcoFlow private app API client — reads PowerStream PV power via MQTT.

The PowerStream broadcasts an inverter heartbeat (cmd_func=20/cmd_id=1) with
the instantaneous PV input power, but only while a client actively requests the
quota — so we re-publish a get-quota request periodically to keep it talking.
The reported power is integrated over time into daily kWh totals by the caller.
Auth + MQTT flow mirror the Home Assistant integration tolwi/hassio-ecoflow-cloud.
"""
import base64
import logging
import secrets
import ssl
import threading
import time

import certifi
import paho.mqtt.client as mqtt
import requests

from proto import powerstream_pb2

logger = logging.getLogger(__name__)

USER_AGENT = "ecoflow-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

# cmd_func/cmd_id of the inverter heartbeat carrying PV power.
HEARTBEAT_CMD_FUNC = 20
HEARTBEAT_CMD_ID = 1

# AddressId.APP — used as src/dest in the get-quota request.
ADDR_APP = 32
# Re-send the get-quota request on this cadence (seconds) to keep the device
# broadcasting; without it the PowerStream stops publishing when no app watches.
GET_QUOTA_INTERVAL = 60


class EcoflowApiError(Exception):
    pass


class EcoflowAuthError(EcoflowApiError):
    pass


def login(email: str, password: str, host: str) -> tuple[str, str]:
    """Authenticate against the private app API. Returns (token, user_id)."""
    url = f"https://{host}/auth/login"
    body = {
        "email": email,
        "password": base64.b64encode(password.encode()).decode(),
        "scene": "IOT_APP",
        "userType": "ECOFLOW",
    }
    headers = {"lang": "en_US", "content-type": "application/json", "User-Agent": USER_AGENT}
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    if resp.status_code in (401, 403):
        raise EcoflowAuthError(f"Login rejected: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("message", "")).lower() != "success":
        raise EcoflowAuthError(f"Login failed: {data.get('message')}")
    payload = data["data"]
    return payload["token"], payload["user"]["userId"]


def get_mqtt_certification(token: str, host: str) -> dict:
    """Fetch MQTT broker credentials. Returns dict with url, port, user, password."""
    url = f"https://{host}/iot-auth/app/certification"
    headers = {
        "lang": "en_US",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "User-Agent": USER_AGENT,
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code in (401, 403):
        raise EcoflowAuthError(f"Certification rejected: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()["data"]
    return {
        "url": data["url"],
        "port": int(data["port"]),
        "user": data["certificateAccount"],
        "password": data["certificatePassword"],
    }


def decode_pv_power(payload: bytes) -> float | None:
    """Decode an MQTT payload, returning total PV power in watts if it is a heartbeat.

    PV watts are reported in deci-watts (value / 10). Returns None for other messages.
    """
    packet = powerstream_pb2.PowerStreamSendHeaderMsg()
    try:
        packet.ParseFromString(payload)
    except Exception:
        return None

    for message in packet.msg:
        if message.cmd_func != HEARTBEAT_CMD_FUNC or message.cmd_id != HEARTBEAT_CMD_ID:
            continue
        hb = powerstream_pb2.PowerStreamInverterHeartbeat()
        try:
            hb.ParseFromString(message.pdata)
        except Exception:
            continue
        return (hb.pv1_input_watts + hb.pv2_input_watts) / 10
    return None


def build_get_quota_request(device_sn: str) -> bytes:
    """Build the protobuf "get latest quota" request (cmd_func=20/cmd_id=1).

    Publishing it keeps the device broadcasting its heartbeat. Mirrors
    tolwi/hassio-ecoflow-cloud.
    """
    packet = powerstream_pb2.PowerStreamSendHeaderMsg()
    msg = packet.msg.add()
    msg.src = ADDR_APP
    msg.dest = ADDR_APP
    msg.cmd_func = HEARTBEAT_CMD_FUNC
    msg.cmd_id = HEARTBEAT_CMD_ID
    msg.data_len = 0
    msg.seq = int(time.time())
    msg.device_sn = device_sn
    msg.from_ = "dashboard"
    return packet.SerializeToString()


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
