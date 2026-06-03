"""Generic MQTT power-sensor slice (config-driven, multi-sensor).

One self-contained vertical slice that replaces the old per-device Cumulus and
Lave-linge slices: every Z2M device that exposes only instantaneous power (W) and
no energy counter is declared in a single env var and integrated the same way —
report a power -> integrate into daily kWh -> one bottom-table row each.

Config: POWER_SENSORS = "topic:Display Name;topic2:Other Name" (`;` separates
sensors, the first `:` of each entry separates the MQTT topic from its label).
Broker host/port/credentials are shared (app.config); this slice owns the topics.
"""
import logging
import os
import time
import unicodedata
from collections import namedtuple
from datetime import datetime, timedelta

from app import db
from app.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ

from .mqtt.listener import PowerMqttListener

logger = logging.getLogger(__name__)

Sensor = namedtuple("Sensor", "slug topic name")

# Legacy single-device tables migrated into the shared daily_power table once.
# The target slugs match _slugify() of the recommended display names, so history
# re-attaches as long as those names are kept in POWER_SENSORS.
_LEGACY_TABLES = (("daily_cumulus", "cumulus"), ("daily_washer", "lave-linge"))

NA_THRESHOLD_KWH = 0.05
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes


def _slugify(name: str) -> str:
    """Lowercase, accent-stripped, space-collapsed slug for storage keys."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return "-".join(ascii_name.lower().split())


def _parse_sensors(raw: str) -> list:
    """Parse "topic:Name;topic2:Name 2" into a list of Sensor; skip malformed."""
    sensors = []
    seen = set()
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning("POWER_SENSORS entry ignored (no ':' topic/name): %r", entry)
            continue
        topic, name = entry.split(":", 1)
        topic, name = topic.strip(), name.strip()
        if not topic or not name:
            logger.warning("POWER_SENSORS entry ignored (empty topic or name): %r", entry)
            continue
        slug = _slugify(name)
        if slug in seen:
            logger.warning("POWER_SENSORS duplicate slug %r ignored: %r", slug, entry)
            continue
        seen.add(slug)
        sensors.append(Sensor(slug, topic, name))
    return sensors


POWER_SENSORS = os.environ.get("POWER_SENSORS", "")
SENSORS = _parse_sensors(POWER_SENSORS)
ENABLED = bool(MQTT_HOST) and bool(SENSORS)

# Per-sensor integration state (power -> daily kWh). Only each sensor's MQTT
# listener thread touches its own entry, so no lock is needed.
_states: dict = {}
_last_report: dict = {}


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the shared daily_power table and migrate legacy tables once."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_power (
            slug TEXT NOT NULL,
            date TEXT NOT NULL,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (slug, date)
        )"""
    )
    for table, slug in _LEGACY_TABLES:
        _migrate_legacy(conn, table, slug)
    conn.commit()
    conn.close()


def _migrate_legacy(conn, table: str, slug: str):
    """One-time copy of a legacy single-device table into daily_power[slug].

    Idempotent: skips if the table is gone or daily_power already holds the slug.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return
    already = conn.execute(
        "SELECT 1 FROM daily_power WHERE slug=? LIMIT 1", (slug,)
    ).fetchone()
    if already:
        return
    rows = conn.execute(f"SELECT date, cons_wh, fetched_at FROM {table}").fetchall()
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO daily_power (slug, date, cons_wh, fetched_at) VALUES (?, ?, ?, ?)",
        [(slug, d, wh, at) for d, wh, at in rows],
    )
    logger.info("Migrated %d rows from %s into daily_power[%s]", len(rows), table, slug)


def _make_on_power(slug: str):
    """Build the MQTT callback that integrates one sensor's power into daily kWh."""

    def _on_power(watts: float):
        now = datetime.now(PARIS_TZ)
        today = now.strftime("%Y-%m-%d")
        st = _states.setdefault(slug, {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0})

        if st["date"] != today:
            if st["date"] is not None:
                db.upsert_power(slug, st["date"], st["wh"])  # flush the finished day
            tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            existing = db.get_cached_power(slug, today, tomorrow)
            st["date"] = today
            st["wh"] = existing[0]["cons_kwh"] * 1000 if existing else 0.0
            st["last_ts"] = None
            st["last_persist"] = 0.0

        if st["last_ts"] is not None:
            dt_h = (now - st["last_ts"]).total_seconds() / 3600
            if dt_h > 0:
                st["wh"] += watts * min(dt_h, MAX_SAMPLE_GAP_H)
        st["last_ts"] = now

        mono = time.monotonic()
        if mono - st["last_persist"] >= PERSIST_INTERVAL:
            db.upsert_power(slug, today, st["wh"])
            st["last_persist"] = mono
        _last_report[slug] = now.isoformat()

    return _on_power


def start():
    """Start one MQTT listener per configured sensor, else log and do nothing."""
    if not ENABLED:
        logger.info("Power sensors disabled (set MQTT_HOST + POWER_SENSORS to enable)")
        return None
    listeners = []
    for s in SENSORS:
        listener = PowerMqttListener(
            s.slug, MQTT_HOST, MQTT_PORT, s.topic, MQTT_USERNAME, MQTT_PASSWORD,
            _make_on_power(s.slug),
        )
        listener.start()
        listeners.append(listener)
        logger.info("Power MQTT listener started (%s) on %s:%d (%s)",
                    s.slug, MQTT_HOST, MQTT_PORT, s.topic)
    return listeners


def _sensor_stats(slug: str, today, today_str: str) -> dict:
    """Yesterday's kWh, recent daily average and trend for one sensor."""
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    yesterday_rows = db.get_cached_power(slug, yesterday_str, today_str)
    yesterday_kwh = yesterday_rows[0]["cons_kwh"] if yesterday_rows else 0.0

    past = [r["cons_kwh"] for r in db.get_cached_power(slug, nine_ago, today_str)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg = sum(past) / len(past) if past else 0.0

    # Trend: last 9 days vs the 28 days before them (mirrors the solar stats).
    prev_start = (today - timedelta(days=37)).strftime("%Y-%m-%d")
    prev = [r["cons_kwh"] for r in db.get_cached_power(slug, prev_start, nine_ago)
            if r["cons_kwh"] >= NA_THRESHOLD_KWH]
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100, 1) if avg_prev > 0 else 0

    return {
        "yesterday_text": f"{yesterday_kwh:.1f}",
        "avg_text": f"{avg:.1f}" if past else "N/A",
        "trend_pct": trend_pct,
    }


def attach(data: dict):
    """Attach one bottom-table entry per sensor (yesterday kWh + recent average).

    Integrated from each device's reported power (no energy counter); history
    starts at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    data["power_sensors"] = [
        {"name": s.name, **_sensor_stats(s.slug, today, today_str)} for s in SENSORS
    ]


def status() -> dict:
    return {"power_enabled": ENABLED, "last_power": dict(_last_report)}
