"""Water meter MQTT transport: reads the cumulative index (m³) from the topic
published by the ESPHome wM-Bus reader.

The meter pushes its index as it transmits (roughly every ≤30 min), so —
unlike the Cumulus contactor — there is nothing to re-request; we just listen.
"""
import json
import logging

from app.module.mqtt import MqttListener

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


class WaterMqttListener(MqttListener):
    """Background thread reading the water index (m³) from an MQTT topic.

    Calls on_index(m3) on each reported value. Reconnects automatically.
    """

    def __init__(self, host, port, topic, username, password, on_index):
        super().__init__(host, port, topic, username, password, on_index,
                         label="Water", thread_name="water-mqtt")

    def _parse(self, payload: bytes):
        return _parse_index(payload)
