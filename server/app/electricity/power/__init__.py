"""Power sub-domain of electricity — generic MQTT power sensors (config-driven).

Every Z2M device that exposes only instantaneous power (W) and no energy counter
is declared in a single env var and integrated the same way — report a power ->
integrate into daily kWh -> one bottom-table row each.

Config: POWER_SENSORS = "topic:Display Name;topic2:Other Name" (`;` separates
sensors, the first `:` of each entry separates the MQTT topic from its label).
Broker host/port/credentials are shared (system.config); this sub-domain owns the
topics.

**Grouping**: several topics that share the same label are summed into one
bottom-table row (e.g. four plugs all named `Salon` -> a single `Salon` total).
Each topic keeps its own MQTT listener and integrator (no shared state, no lock);
the sum is computed at display time over the group's per-topic daily series. A
lone sensor stores under `_slugify(name)` (unchanged, history preserved); the
members of a multi-topic group get a per-topic suffix so they never collide.

The point of entry keeps the config parsing and re-exports the slice API,
delegating writes (integrators, listeners) to command and reads (group stats,
attach) to query — the same layout as every sibling domain.
"""
import os
from collections import Counter, namedtuple

from app.system.config import MQTT_HOST
from app.module.sensors import parse_entries, slugify as _slugify, topic_suffixed_slug

Sensor = namedtuple("Sensor", "slug topic name")


def _parse_sensors(raw: str) -> list:
    """Parse "topic:Name;topic2:Name 2" into a list of Sensor; skip malformed.

    Topics sharing a name form a group summed under that label. A lone name keeps
    the bare `_slugify(name)` storage slug (backward compatible); each member of a
    multi-topic group gets a `_slugify(name)-_slugify(topic)` slug so they don't
    collide. The group total is the sum of its members, so which member owns which
    slug is irrelevant to the displayed value.
    """
    parsed = parse_entries(raw, "POWER_SENSORS")  # (topic, name), deduped by topic
    name_counts = Counter(name for _, name in parsed)
    return [
        Sensor(topic_suffixed_slug(name, topic) if name_counts[name] > 1 else _slugify(name),
               topic, name)
        for topic, name in parsed
    ]


def _groups(sensors: list) -> list:
    """Group sensors by display name, preserving each name's first-appearance
    order. Returns an ordered list of (name, [slug, ...])."""
    by_name: dict = {}
    order = []
    for s in sensors:
        if s.name not in by_name:
            by_name[s.name] = []
            order.append(s.name)
        by_name[s.name].append(s.slug)
    return [(name, by_name[name]) for name in order]


POWER_SENSORS = os.environ.get("POWER_SENSORS", "")
SENSORS = _parse_sensors(POWER_SENSORS)
ENABLED = bool(MQTT_HOST) and bool(SENSORS)


def enabled() -> bool:
    return ENABLED


from app.electricity.power.command import init_schema, start  # noqa: E402
from app.electricity.power.query import attach, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status",
    "ENABLED", "SENSORS", "Sensor",
]
