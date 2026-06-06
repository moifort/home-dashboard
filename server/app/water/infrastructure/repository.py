"""Water domain repository — the only place that touches the water tables.

Stores the meter's latest cumulative index (m³) per day; daily consumption is
derived as an index diff at read time (see rules.build_water_panel). The
water_samples table keeps the same index per 30-min slot for the intraday
litre profiles.
"""
from datetime import datetime, timedelta

from app.module.db import connect
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_water + water_samples tables (idempotent)."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_water (
            date TEXT PRIMARY KEY,
            index_m3 REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    # One row per 30-min slot: the slot's last cumulative index (m³) — litres
    # per slot are derived as index diffs at read time. Unlimited retention —
    # feeds the mini intraday graph under each Eau bar.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS water_samples (
            ts TEXT PRIMARY KEY,
            index_m3 REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def get_cached_water(start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, index_m3 FROM daily_water WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "index_m3": r[1]} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_water(date: str, index_m3: float):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_water (date, index_m3, fetched_at) VALUES (?, ?, ?)",
        (date, index_m3, now),
    )
    conn.commit()
    conn.close()


def insert_water_sample(ts: str, index_m3: float):
    """Persist the slot's latest cumulative index (ts = 30-min slot start, ISO
    local). INSERT OR REPLACE keeps the last reading of the slot."""
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO water_samples (ts, index_m3) VALUES (?, ?)",
        (ts, index_m3),
    )
    conn.commit()
    conn.close()


def get_water_litre_profiles(start: str, end: str) -> dict[str, list]:
    """Per-date intraday litre profile: 48 half-hour slots of litres consumed
    (index diff vs the previous reported slot), None where the slot has no
    sample. Only dates with at least one derived value are returned — feeds the
    mini intraday graph under each Eau bar.

    Reads one extra day before `start` so the first slot diffs against the last
    reading of the previous day (midnight crossing). A quiet meter leaves slot
    gaps — the jump lands on the next slot that reports (the same carry-forward
    convention as the daily diff). A negative diff (meter reset) yields no
    litres but still re-baselines.
    """
    baseline_start = (datetime.fromisoformat(start) - timedelta(days=1)).strftime("%Y-%m-%d")
    conn = connect()
    cur = conn.execute(
        "SELECT ts, index_m3 FROM water_samples WHERE ts >= ? AND ts < ? ORDER BY ts",
        (baseline_start, end),
    )
    profiles: dict[str, list] = {}
    prev_index = None
    for ts, index_m3 in cur.fetchall():
        if prev_index is not None and ts[:10] >= start:
            delta = index_m3 - prev_index
            if delta >= 0:
                dt = datetime.fromisoformat(ts)
                slot = dt.hour * 2 + (1 if dt.minute >= 30 else 0)
                profiles.setdefault(ts[:10], [None] * 48)[slot] = round(delta * 1000, 1)
        prev_index = index_m3
    conn.close()
    return profiles
