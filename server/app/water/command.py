"""Water domain commands (write side): schema init, MQTT listener, index upsert."""
import logging
from datetime import datetime

from app.system.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ
from app.water.infrastructure import repository
from app.water.infrastructure.mqtt import WaterMqttListener

logger = logging.getLogger(__name__)

# Runtime state: last time the meter reported (surfaced by query.status()).
last_report = ""


def init_schema():
    """Create the daily_water table (idempotent)."""
    repository.init_schema()


def _on_water_index(m3: float):
    """MQTT callback: store today's latest cumulative index (m³). INSERT OR
    REPLACE keeps the last value of the day, which is all the diff needs."""
    global last_report
    now = datetime.now(PARIS_TZ)
    repository.upsert_water(now.strftime("%Y-%m-%d"), m3)
    last_report = now.isoformat()


def start():
    """Start the water MQTT listener if enabled, else log and do nothing."""
    from app.water import ENABLED, TOPIC

    if not ENABLED:
        logger.info("Water integration disabled (set MQTT_HOST + WATER_TOPIC to enable)")
        return None
    listener = WaterMqttListener(
        MQTT_HOST, MQTT_PORT, TOPIC, MQTT_USERNAME, MQTT_PASSWORD, _on_water_index,
    )
    listener.start()
    logger.info("Water MQTT listener started on %s:%d (%s)", MQTT_HOST, MQTT_PORT, TOPIC)
    return listener
