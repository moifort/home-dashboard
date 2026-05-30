"""Cumulus MQTT transport: reads `power` from the Zigbee2MQTT contactor topic.

Z2M publishes power on change; we also re-request it periodically (a `get`) so
samples keep flowing during long, steady heating periods.
"""
import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# Re-request power on this cadence (seconds) so integration keeps getting
# samples even when the load is steady and Z2M would otherwise stay quiet.
GET_INTERVAL = 60


def _parse_power(payload: bytes) -> float | None:
    """Extract the numeric `power` (W) from a Z2M JSON device message."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    power = data.get("power")
    if isinstance(power, (int, float)):
        return float(power)
    return None


class CumulusMqttListener:
    """Background thread reading `power` from a Zigbee2MQTT device topic.

    Calls on_power(watts) on each reported value. Reconnects automatically.
    """

    def __init__(self, host, port, topic, username, password, on_power):
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._on_power = on_power
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="cumulus-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning("Cumulus MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)
        get_topic = f"{self._topic}/get"

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("Cumulus MQTT connect failed: %s", reason_code)
                return
            c.subscribe(self._topic, qos=0)
            c.publish(get_topic, json.dumps({"power": ""}), qos=0)
            logger.info("Cumulus MQTT connected, subscribed to %s", self._topic)

        def on_message(c, userdata, msg):
            watts = _parse_power(msg.payload)
            if watts is not None:
                try:
                    self._on_power(watts)
                except Exception:
                    logger.exception("on_power callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(self._host, self._port, keepalive=30)

        last_poll = time.monotonic()
        while not self._stop.is_set():
            client.loop(timeout=1.0)
            if time.monotonic() - last_poll >= GET_INTERVAL:
                client.publish(get_topic, json.dumps({"power": ""}), qos=0)
                last_poll = time.monotonic()
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
