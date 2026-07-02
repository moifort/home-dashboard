"""Generic power-sensor MQTT transport: reads `power` from a Z2M device topic.

Z2M publishes power on change; we also re-request it periodically (a `get`) so
samples keep flowing during long, steady loads. One listener runs per configured
sensor (its topic); the integration owns the power -> energy accumulation.
"""
import json
import logging
import time

from app.module.mqtt import MqttListener

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


class PowerMqttListener(MqttListener):
    """Background thread reading `power` from a Zigbee2MQTT device topic.

    Calls on_power(watts) on each reported value. Reconnects automatically.
    Requests `power` at subscribe time then every GET_INTERVAL so integration
    keeps getting samples during long, steady loads.
    """

    def __init__(self, slug, host, port, topic, username, password, on_power):
        super().__init__(host, port, topic, username, password, on_power,
                         label=f"Power ({slug})", thread_name=f"power-{slug}-mqtt")
        self._get_topic = f"{topic}/get"
        self._last_poll = 0.0

    def _parse(self, payload: bytes):
        return _parse_power(payload)

    def _request_power(self, client):
        client.publish(self._get_topic, json.dumps({"power": ""}), qos=0)
        self._last_poll = time.monotonic()

    def _on_subscribed(self, client):
        self._request_power(client)

    def _tick(self, client):
        if time.monotonic() - self._last_poll >= GET_INTERVAL:
            self._request_power(client)
