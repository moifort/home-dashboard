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


def test_relative_time_buckets():
    now = datetime(2026, 6, 2, 14, 30, tzinfo=PARIS_TZ)

    def ago(**kw):
        return (now - timedelta(**kw)).isoformat()

    assert rules.relative_time(ago(seconds=20), now) == "0min"
    assert rules.relative_time(ago(minutes=12), now) == "12min"
    assert rules.relative_time(ago(hours=3), now) == "3h"
    assert rules.relative_time(ago(hours=3, minutes=59), now) == "3h"
    assert rules.relative_time(ago(days=2, hours=5), now) == "2j"
    # A future timestamp (clock skew) clamps to "0min".
    assert rules.relative_time(ago(minutes=-5), now) == "0min"


def test_relative_time_missing_or_garbage():
    now = datetime(2026, 6, 2, 14, 30, tzinfo=PARIS_TZ)
    assert rules.relative_time(None, now) is None
    assert rules.relative_time("not-a-date", now) is None
    assert rules.relative_time("2026-06-02T14:00:00+02:00", None) is None


def test_attach_exposes_relative_last_seen(tmp_path, monkeypatch):
    _use_tmp_db(tmp_path, monkeypatch)
    today = datetime.now(PARIS_TZ).date()
    repository.upsert_day("ficus", today.strftime("%Y-%m-%d"), {"moisture": 60.0})
    data = {}
    query.attach(data, [Sensor("ficus", "zigbee2mqtt/ficus", "Ficus", 50.0)])
    # Written "now", so the card reports a fresh last-seen rather than None.
    assert data["plants"][0]["last_seen_text"] == "0min"


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
