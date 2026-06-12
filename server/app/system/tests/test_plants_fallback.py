"""Plants card fallback to the last known reading.

A soil sensor reports only once or twice a day, so right after the midnight
rollover today's row does not exist yet and the card would dash out for hours.
A soil reading is a slowly-moving instantaneous state: the freshest known value
within a short lookback beats an em dash.
"""
from datetime import datetime, timedelta

from app.module import db
from app.plants import Sensor, query, rules
from app.plants.infrastructure import repository
from app.system.config import PARIS_TZ


def test_latest_metrics_takes_freshest_value_per_field():
    rows = [
        {"moisture": None, "temperature": 25.0},   # today: partial frame only
        None,                                       # yesterday: no row
        {"moisture": 40.0, "temperature": 21.0},    # two days ago: full
    ]
    merged = rules.latest_metrics(rows)
    assert merged["temperature"] == 25.0  # today's reading wins
    assert merged["moisture"] == 40.0     # filled from the older row


def test_latest_metrics_all_unknown_is_empty():
    assert rules.latest_metrics([None, {}, {"moisture": None}]) == {}


def _use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    repository.init_schema()


def test_attach_falls_back_to_yesterdays_reading(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    yesterday = datetime.now(PARIS_TZ).date() - timedelta(days=1)
    repository.upsert_day("ficus", yesterday.strftime("%Y-%m-%d"),
                          {"moisture": 40.0, "temperature": 21.0,
                           "illuminance": 800.0})
    data = {}
    query.attach(data, [Sensor("ficus", "zigbee2mqtt/ficus", "Ficus", 50.0)])
    card = data["plants"][0]
    assert card["moisture_text"] == "40"
    assert card["temperature_text"] == "21"
    assert card["needs_water"] is True  # 40 < 50, judged on the fallback value


def test_attach_ignores_readings_older_than_lookback(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    stale = datetime.now(PARIS_TZ).date() - timedelta(days=3)
    repository.upsert_day("ficus", stale.strftime("%Y-%m-%d"),
                          {"moisture": 40.0})
    data = {}
    query.attach(data, [Sensor("ficus", "zigbee2mqtt/ficus", "Ficus", 50.0)])
    card = data["plants"][0]
    assert card["moisture_text"] == "—"  # a dead sensor must still dash out
    assert card["needs_water"] is False
