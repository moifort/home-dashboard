"""Water meter MQTT transport: reads the cumulative index (m³) from the topic
published by the ESPHome wM-Bus reader.

The meter pushes its index as it transmits (roughly every ≤30 min), so —
unlike the Cumulus contactor — there is nothing to re-request; we just listen.
"""
import json
import logging
import threading

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


def _parse_index(payload: bytes) -> float | None:
    """Extract the cumulative water index (m³) from an MQTT message.

    ESPHome publishes the sensor state as a bare float string; we also accept a
    JSON object with a `value` field for robustness against alternate setups.
    """
    text = payload.decode(errors="ignore").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        pass
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    value = data.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


class WaterMqttListener:
    """Background thread reading the water index (m³) from an MQTT topic.

    Calls on_index(m3) on each reported value. Reconnects automatically.
    """

    def __init__(self, host, port, topic, username, password, on_index):
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._on_index = on_index
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="water-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning("Water MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("Water MQTT connect failed: %s", reason_code)
                return
            c.subscribe(self._topic, qos=0)
            logger.info("Water MQTT connected, subscribed to %s", self._topic)

        def on_message(c, userdata, msg):
            m3 = _parse_index(msg.payload)
            if m3 is not None:
                try:
                    self._on_index(m3)
                except Exception:
                    logger.exception("on_index callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(self._host, self._port, keepalive=30)

        while not self._stop.is_set():
            client.loop(timeout=1.0)
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
