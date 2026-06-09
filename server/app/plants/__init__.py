"""Plants domain — Zigbee soil sensors (config-driven, multi-device).

Every Zigbee2MQTT plant sensor that reports instantaneous states (soil moisture %,
temperature °C, illuminance lux, fertility µS/cm) is declared in a single env var
and shown as one gutter line — its current soil moisture + a 7-day moisture spark.

Config: PLANTS_SENSORS = "topic:Display Name[:threshold];topic2:Other Name[:40]"
(`;` separates sensors; within one entry the first field is the MQTT topic, then
the display name, and an optional trailing numeric field is the soil-moisture
floor in % — below it the plant shows a red water drop "needs watering"). The
broker host/port/credentials are shared (system.config); this domain owns the
topics. One MQTT listener and one slug per sensor — 1 sensor = 1 plant, no grouping
(unlike the power sensors, you don't sum soil-moisture readings).

Unlike the power sensors, a reading is an instantaneous state (not a cumulative
counter): we keep the latest value of each metric for the current day rather than
integrating. All four metrics are persisted; the on-screen card shows soil
moisture (+ a red drop under the threshold), fertility and illuminance.
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

Sensor = namedtuple("Sensor", "slug topic name threshold")


def _slugify(name: str) -> str:
    """Lowercase, accent-stripped, space-collapsed slug for storage keys."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return "-".join(ascii_name.lower().split())


def _parse_threshold(token: str):
    """A trailing numeric field (optionally a trailing '%') as a float, else None."""
    try:
        return float(token.strip().rstrip("%").strip())
    except ValueError:
        return None


def _parse_sensors(raw: str) -> list:
    """Parse "topic:Name[:threshold];topic2:Name 2[:40]" into a list of Sensor.

    Each entry is `topic:name[:threshold]`. The topic never contains a colon
    (Z2M topics use '/'), so we split on ':' and read an optional trailing numeric
    field as the soil-moisture floor (%). One sensor per topic (deduped); each is
    its own plant. The storage slug is `_slugify(name)`; a rare name collision
    falls back to a per-topic suffix. No grouping/summing (states, not counters)."""
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
        parts = entry.split(":")
        topic = parts[0].strip()
        rest = parts[1:]
        # A trailing numeric field is the moisture threshold; the rest is the name.
        threshold = None
        if len(rest) >= 2 and _parse_threshold(rest[-1]) is not None:
            threshold = _parse_threshold(rest[-1])
            name = ":".join(rest[:-1]).strip()
        else:
            name = ":".join(rest).strip()
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
        sensors.append(Sensor(slug, topic, name, threshold))
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
