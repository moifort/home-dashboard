"""Plants domain repository — the only place that touches daily_plants.

One row per (slug, date). Numeric metrics (soil moisture, temperature,
illuminance, fertility) and the battery_state status string are instantaneous
states, not counters — an upsert keeps the day's latest of each: numeric metrics
merge (a frame overwrites only the ones it carries, so metrics arriving in
separate Z2M frames accumulate), the status string overwrites when present. No
backfill: history starts at first connection.
"""
import logging
from datetime import datetime

from app.module.db import transaction
from app.system.config import PARIS_TZ

logger = logging.getLogger(__name__)

# Numeric metrics (REAL) merged per frame; the status string (TEXT) overwritten.
_METRICS = ("moisture", "temperature", "illuminance", "fertility")
_STATUS = ("battery_state",)
_FIELDS = _METRICS + _STATUS


def init_schema():
    """Create the shared daily_plants table (+ add later columns idempotently)."""
    with transaction() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_plants (
                slug TEXT NOT NULL,
                date TEXT NOT NULL,
                moisture REAL,
                temperature REAL,
                illuminance REAL,
                fertility REAL,
                battery_state TEXT,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (slug, date)
            )"""
        )
        # battery_state was added after the table's first shape; add it to a
        # pre-existing dev DB so older daily_plants rows keep working (NULL status).
        # A legacy water_warning column may still linger on old DBs — left untouched,
        # never read or written (watering is now soil-moisture vs threshold).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_plants)")}
        for col in _STATUS:
            if col not in cols:
                conn.execute(f"ALTER TABLE daily_plants ADD COLUMN {col} TEXT")


def get_cached_plants(slug: str, start: str, end: str) -> list[dict]:
    """Daily rows for one plant over [start, end), oldest first (moisture spark)."""
    with transaction() as conn:
        cur = conn.execute(
            "SELECT date, moisture, temperature, illuminance, fertility FROM daily_plants "
            "WHERE slug = ? AND date >= ? AND date < ? ORDER BY date",
            (slug, start, end),
        )
        return [{"date": r[0], "moisture": r[1], "temperature": r[2],
                 "illuminance": r[3], "fertility": r[4]} for r in cur.fetchall()]


def get_last_seen(slug: str) -> str | None:
    """The most recent write timestamp (`fetched_at`) for this plant, i.e. when
    it last reported, or None if it never has. Persisted, so it survives a
    restart (unlike the in-memory /status tracker)."""
    with transaction() as conn:
        cur = conn.execute(
            "SELECT MAX(fetched_at) FROM daily_plants WHERE slug = ?", (slug,)
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_day(slug: str, date: str) -> dict | None:
    """The day's stored metrics + status for one plant, or None if it never
    reported."""
    with transaction() as conn:
        cur = conn.execute(
            "SELECT moisture, temperature, illuminance, fertility, battery_state "
            "FROM daily_plants WHERE slug = ? AND date = ?",
            (slug, date),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(_FIELDS, row))


def upsert_day(slug: str, date: str, fields: dict):
    """Insert or update the day's row. Numeric metrics merge (only the ones
    present in `fields` are written; the rest keep their stored value); status
    strings overwrite when present, else keep the stored value."""
    now = datetime.now(PARIS_TZ).isoformat()
    with transaction() as conn:
        cur = conn.execute(
            "SELECT moisture, temperature, illuminance, fertility, battery_state "
            "FROM daily_plants WHERE slug = ? AND date = ?",
            (slug, date),
        )
        row = cur.fetchone()
        merged = {c: (row[i] if row else None) for i, c in enumerate(_FIELDS)}
        for c in _FIELDS:
            if fields.get(c) is not None:
                merged[c] = fields[c]
        conn.execute(
            "INSERT OR REPLACE INTO daily_plants "
            "(slug, date, moisture, temperature, illuminance, fertility, "
            "battery_state, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, date, merged["moisture"], merged["temperature"], merged["illuminance"],
             merged["fertility"], merged["battery_state"], now),
        )
