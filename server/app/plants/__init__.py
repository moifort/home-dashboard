"""Plants domain — Zigbee soil sensors (config-driven, multi-device).

Every Zigbee2MQTT plant sensor that reports instantaneous states (soil moisture %,
temperature °C, illuminance lux, fertility µS/cm) is declared in a single env var
and shown as one gutter line — its current soil moisture + a 7-day moisture spark.

Config: PLANTS_SENSORS = "topic:Display Name;topic2:Other Name" (`;` separates
sensors, the first `:` of each entry splits the MQTT topic from its label). The
broker host/port/credentials are shared (system.config); this domain owns the
topics. One MQTT listener and one slug per sensor — 1 sensor = 1 plant, no grouping
(unlike the power sensors, you don't sum soil-moisture readings).

Unlike the power sensors, a reading is an instantaneous state (not a cumulative
counter): we keep the latest value of each metric for the current day rather than
integrating. All four metrics are persisted; the on-screen card shows soil
moisture, temperature and illuminance, plus a red water drop when the device's
`water_warning` flags it and a red battery icon when `battery_state` is low.
"""
import logging
import os
import unicodedata
from collections import namedtuple

from app.system.config import MQTT_HOST

from app.plants import command as _command
from app.plants import query as _query
from app.plants.infrastructure import repository

logger = logging.getLogger(__name__)

Sensor = namedtuple("Sensor", "slug topic name")


def _slugify(name: str) -> str:
    """Lowercase, accent-stripped, space-collapsed slug for storage keys."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return "-".join(ascii_name.lower().split())


def _parse_sensors(raw: str) -> list:
    """Parse "topic:Name;topic2:Name 2" into a list of Sensor; skip malformed.

    One sensor per topic (deduped by topic); each is its own plant. The storage
    slug is `_slugify(name)`; a rare name collision falls back to a per-topic
    suffix so two plants never share a row. No grouping/summing (states, not
    counters)."""
    sensors = []
    seen_topics = set()
    seen_slugs = set()
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning("PLANTS_SENSORS entry ignored (no ':' topic/name): %r", entry)
            continue
        topic, name = entry.split(":", 1)
        topic, name = topic.strip(), name.strip()
        if not topic or not name:
            logger.warning("PLANTS_SENSORS entry ignored (empty topic or name): %r", entry)
            continue
        if topic in seen_topics:
            logger.warning("PLANTS_SENSORS duplicate topic %r ignored: %r", topic, entry)
            continue
        slug = _slugify(name)
        if slug in seen_slugs:
            slug = f"{slug}-{_slugify(topic.replace('/', ' '))}"
        seen_topics.add(topic)
        seen_slugs.add(slug)
        sensors.append(Sensor(slug, topic, name))
    return sensors


PLANTS_SENSORS = os.environ.get("PLANTS_SENSORS", "")
SENSORS = _parse_sensors(PLANTS_SENSORS)
ENABLED = bool(MQTT_HOST) and bool(SENSORS)


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the shared daily_plants table."""
    repository.init_schema()


def start():
    """Start one MQTT listener per configured plant, else log and do nothing."""
    if not ENABLED:
        logger.info("Plant sensors disabled (set MQTT_HOST + PLANTS_SENSORS to enable)")
        return None
    return _command.start(SENSORS)


def attach(data: dict):
    """Attach one render entry per plant (current soil moisture + 7-day spark)."""
    _query.attach(data, SENSORS)


def status() -> dict:
    return {"plants_enabled": ENABLED, "last_plant": _command.status_report()}
