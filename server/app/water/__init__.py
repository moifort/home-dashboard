"""Water domain — water-meter daily consumption ("Eau" chart).

Turns a wM-Bus meter's cumulative index (m³), pushed over MQTT, into a
daily-litres chart plus a monthly total and cost. The point of entry exposes the
uniform slice API (enabled / init_schema / start / attach / status), delegating
reads to query, lifecycle/writes to command, and the m³→litres math to rules.
Remove the whole folder to drop the water reading.
"""
import os

from app.system.config import MQTT_HOST
from app.module.format import env_float

# Broker host/port/credentials are shared (system.config); this domain owns its topic.
TOPIC = os.environ.get("WATER_TOPIC", "")
PRICE_M3 = env_float("WATER_PRICE_M3", 0.0)

ENABLED = bool(MQTT_HOST) and bool(TOPIC)


def enabled() -> bool:
    return ENABLED


from app.water.command import init_schema, start  # noqa: E402
from app.water.query import attach, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status",
    "ENABLED", "TOPIC", "PRICE_M3",
]
