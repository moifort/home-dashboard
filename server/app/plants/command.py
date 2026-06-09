"""Plants writes — persist each sensor's latest reading into the daily row.

A plant reading is an instantaneous state, so there's no integration: each
message just refreshes the day's stored metrics (latest value wins). One MQTT
listener per sensor; each listener thread owns its slug, so no shared state and
no lock.
"""
import logging
from datetime import datetime

from app.system.config import (MQTT_HOST, MQTT_PASSWORD, MQTT_PORT,
                               MQTT_USERNAME, PARIS_TZ)
from app.plants.infrastructure import repository
from app.plants.infrastructure.mqtt import PlantsMqttListener

logger = logging.getLogger(__name__)

# Last report time per slug (for the /status endpoint).
_last_report: dict = {}


def _make_on_reading(slug: str):
    """Build the MQTT callback that stores one plant's latest daily reading."""

    def _on_reading(reading: dict):
        now = datetime.now(PARIS_TZ)
        repository.upsert_day(slug, now.strftime("%Y-%m-%d"), reading)
        _last_report[slug] = now.isoformat()

    return _on_reading


def start(sensors):
    """Start one MQTT listener per configured plant."""
    listeners = []
    for s in sensors:
        listener = PlantsMqttListener(
            s.slug, MQTT_HOST, MQTT_PORT, s.topic, MQTT_USERNAME, MQTT_PASSWORD,
            _make_on_reading(s.slug),
        )
        listener.start()
        listeners.append(listener)
        logger.info("Plant MQTT listener started (%s) on %s:%d (%s)",
                    s.slug, MQTT_HOST, MQTT_PORT, s.topic)
    return listeners


def status_report() -> dict:
    return dict(_last_report)
