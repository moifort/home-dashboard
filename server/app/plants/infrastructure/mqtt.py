"""Plant-sensor MQTT transport: reads soil-sensor metrics from a Z2M device topic.

One listener per configured plant (its topic). Battery soil sensors publish on
their own schedule (often hourly) and don't answer a `/get` poll — so, unlike the
power sensors (which re-request every 60s), we only subscribe and never poll, to
avoid waking them. The domain owns turning a reading into a stored daily row.
"""
import json
import logging

from app.module.mqtt import MqttListener

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


class PlantsMqttListener(MqttListener):
    """Background thread reading soil metrics from a Zigbee2MQTT device topic.

    Calls on_reading({metric: value, ...}) on each message carrying at least one
    known metric. Reconnects automatically; subscribe-only (no `/get` poll).
    """

    def __init__(self, slug, host, port, topic, username, password, on_reading):
        super().__init__(host, port, topic, username, password, on_reading,
                         label=f"Plant ({slug})", thread_name=f"plant-{slug}-mqtt")

    def _parse(self, payload: bytes):
        # An empty reading (no known metric) is skipped, same as unparseable.
        return _parse_reading(payload) or None
