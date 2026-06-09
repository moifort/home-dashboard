"""Unit tests for the plants slice: PLANTS_SENSORS parsing + Z2M payload parsing.

Pure logic, no MQTT/DB: the env-var parser and the message parser are fed raw
inputs. Mirrors test_power_grouping.py but without grouping (1 sensor = 1 plant).
"""
from datetime import date

from app.plants import _parse_sensors, _slugify
from app.plants.infrastructure.mqtt import _parse_reading
from app.plants.rules import build_plant_view


def test_parse_one_sensor():
    sensors = _parse_sensors("zigbee2mqtt/Ficus:Ficus")
    assert len(sensors) == 1
    assert sensors[0].slug == "ficus"
    assert sensors[0].topic == "zigbee2mqtt/Ficus"
    assert sensors[0].name == "Ficus"


def test_name_keeps_extra_colons():
    # Only the first ':' splits topic/name, so a label may contain colons.
    sensors = _parse_sensors("zigbee2mqtt/p1:Plante:Salon")
    assert sensors[0].topic == "zigbee2mqtt/p1"
    assert sensors[0].name == "Plante:Salon"


def test_one_slug_per_plant_no_grouping():
    raw = "zigbee2mqtt/p1:Ficus;zigbee2mqtt/p2:Basilic"
    slugs = [s.slug for s in _parse_sensors(raw)]
    assert slugs == ["ficus", "basilic"]  # distinct names -> distinct slugs, no sum


def test_name_collision_gets_topic_suffix():
    # Two plants sharing a label still get distinct rows (no silent overwrite).
    sensors = _parse_sensors("zigbee2mqtt/p1:Ficus;zigbee2mqtt/p2:Ficus")
    slugs = [s.slug for s in sensors]
    assert slugs[0] == "ficus"
    assert slugs[1] == "ficus-zigbee2mqtt-p2"


def test_duplicate_topic_ignored():
    sensors = _parse_sensors("zigbee2mqtt/p1:Ficus;zigbee2mqtt/p1:Other")
    assert len(sensors) == 1


def test_malformed_entries_skipped():
    assert _parse_sensors("") == []
    assert _parse_sensors("no-colon-here") == []
    assert _parse_sensors("zigbee2mqtt/p1:") == []
    assert _parse_sensors(":Ficus") == []


def test_slugify_strips_accents_and_spaces():
    assert _slugify("Aloé Vera") == "aloe-vera"


def test_parse_reading_z2m_keys():
    reading = _parse_reading(
        b'{"soil_moisture": 45, "temperature": 21.5, "illuminance": 1200, '
        b'"soil_fertility": 18, "battery": 90}'
    )
    assert reading == {"moisture": 45.0, "temperature": 21.5,
                       "illuminance": 1200.0, "fertility": 18.0}


def test_parse_reading_fallback_keys():
    # Mi-Flora-style keys: moisture / illuminance_lux / conductivity.
    reading = _parse_reading(
        b'{"moisture": 30, "illuminance_lux": 800, "conductivity": 22}'
    )
    assert reading == {"moisture": 30.0, "illuminance": 800.0, "fertility": 22.0}


def test_parse_reading_partial_and_garbage():
    assert _parse_reading(b'{"soil_moisture": 50}') == {"moisture": 50.0}
    assert _parse_reading(b"not json") == {}
    assert _parse_reading(b'{"battery": 80}') == {}  # no known metric
    # booleans are not numeric metrics
    assert _parse_reading(b'{"soil_moisture": true}') == {}


def test_parse_reading_real_payload_air_humidity_not_soil():
    # The real device frame: soil_moisture (88) is the moisture; air `humidity`
    # (93) must NOT be read as soil moisture. Status enums are picked up too.
    reading = _parse_reading(
        b'{"linkquality": 60, "soil_moisture": 88, "illuminance": 0, '
        b'"temperature": 23.6, "soil_sampling": 600, "humidity": 93, '
        b'"water_warning": "none", "battery_state": "middle"}'
    )
    assert reading == {"moisture": 88.0, "illuminance": 0.0, "temperature": 23.6,
                       "water_warning": "none", "battery_state": "middle"}


def test_needs_water_from_water_warning():
    today = date(2026, 6, 2)
    dry = build_plant_view("Ficus", {"moisture": 88.0, "water_warning": "warning"}, {}, today)
    assert dry["needs_water"] is True
    ok = build_plant_view("Ficus", {"moisture": 88.0, "water_warning": "none"}, {}, today)
    assert ok["needs_water"] is False
    # No water_warning at all -> no watering flag (no threshold fallback anymore).
    assert build_plant_view("Ficus", {"moisture": 20.0}, {}, today)["needs_water"] is False


def test_low_battery_flag():
    today = date(2026, 6, 2)
    assert build_plant_view("F", {"battery_state": "low"}, {}, today)["low_battery"] is True
    assert build_plant_view("F", {"battery_state": "middle"}, {}, today)["low_battery"] is False
    assert build_plant_view("F", {}, {}, today)["low_battery"] is False
