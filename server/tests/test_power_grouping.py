"""Unit tests for the power slice's topic grouping (POWER_SENSORS parsing).

Pure parsing logic, no DB or font rendering — portable and byte-exact everywhere.
The summed-series behaviour itself is covered by the golden data test, which seeds
a two-topic "Salon" group.
"""
from app.integrations.power import _groups, _parse_sensors


def test_lone_sensor_keeps_bare_name_slug():
    """A name used once stores under _slugify(name) — backward compatible."""
    sensors = _parse_sensors("zigbee2mqtt/Cumulus:Cumulus")
    assert len(sensors) == 1
    assert sensors[0].slug == "cumulus"
    assert sensors[0].name == "Cumulus"


def test_shared_label_groups_topics_with_distinct_slugs():
    """Topics sharing a label become a group; members get per-topic slugs."""
    raw = "zigbee2mqtt/Prise 1:Salon;zigbee2mqtt/Prise B:Salon;zigbee2mqtt/Cumulus:Cumulus"
    sensors = _parse_sensors(raw)
    assert len(sensors) == 3

    slugs = [s.slug for s in sensors]
    assert len(set(slugs)) == 3  # no collisions
    # Grouped members carry a per-topic suffix; the lone sensor stays bare.
    assert slugs == ["salon-zigbee2mqtt-prise-1", "salon-zigbee2mqtt-prise-b", "cumulus"]

    groups = _groups(sensors)
    assert [name for name, _ in groups] == ["Salon", "Cumulus"]  # first-appearance order
    assert groups[0] == ("Salon", ["salon-zigbee2mqtt-prise-1", "salon-zigbee2mqtt-prise-b"])
    assert groups[1] == ("Cumulus", ["cumulus"])


def test_duplicate_topic_is_ignored():
    """The same topic declared twice is deduped (even under different labels)."""
    sensors = _parse_sensors("zigbee2mqtt/Prise 1:Salon;zigbee2mqtt/Prise 1:Bureau")
    assert len(sensors) == 1
    assert sensors[0].name == "Salon"  # first declaration wins
