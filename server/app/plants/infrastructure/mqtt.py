"""Plant-sensor MQTT transport: reads soil-sensor metrics from a Z2M device topic.

One listener per configured plant (its topic). Battery soil sensors publish on
their own schedule (often hourly) and don't answer a `/get` poll — so, unlike the
power sensors (which re-request every 60s), we only subscribe and never poll, to
avoid waking them. The domain owns turning a reading into a stored daily row.
"""
import json
import logging
import threading

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# Z2M / Mi-Flora property-name fallbacks per metric (first present key wins).
# `soil_moisture` is the watering-relevant value; `humidity` is *air* humidity, a
# distinct metric, so it is deliberately NOT a moisture fallback.
_KEYS = {
    "moisture": ("soil_moisture", "moisture"),
    "temperature": ("temperature", "soil_temperature"),
    "illuminance": ("illuminance_lux", "illuminance", "light", "lux"),
    "fertility": ("soil_fertility", "fertility", "conductivity", "soil_ec"),
}


def _parse_reading(payload: bytes) -> dict:
    """Extract whatever of the four metrics a Z2M device message carries."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    reading = {}
    for metric, keys in _KEYS.items():
        for key in keys:
            val = data.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                reading[metric] = float(val)
                break
    # battery_state drives the low-battery flag. The device's water_warning is
    # deliberately not read: watering is decided by soil moisture vs threshold.
    if isinstance(data.get("battery_state"), str):
        reading["battery_state"] = data["battery_state"]
    return reading


class PlantsMqttListener:
    """Background thread reading soil metrics from a Zigbee2MQTT device topic.

    Calls on_reading({metric: value, ...}) on each message carrying at least one
    known metric. Reconnects automatically; subscribe-only (no `/get` poll).
    """

    def __init__(self, slug, host, port, topic, username, password, on_reading):
        self._slug = slug
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._on_reading = on_reading
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name=f"plant-{self._slug}-mqtt", daemon=True
        )
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning(
                    "Plant MQTT session (%s) ended (%s), retrying in 60s", self._slug, exc
                )
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("Plant MQTT connect failed (%s): %s", self._slug, reason_code)
                return
            c.subscribe(self._topic, qos=0)
            logger.info("Plant MQTT connected (%s), subscribed to %s", self._slug, self._topic)

        def on_message(c, userdata, msg):
            reading = _parse_reading(msg.payload)
            if reading:
                try:
                    self._on_reading(reading)
                except Exception:
                    logger.exception("on_reading callback failed (%s)", self._slug)

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
