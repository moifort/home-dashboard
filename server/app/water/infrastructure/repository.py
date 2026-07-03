"""Water domain repository — the only place that touches the water tables.

Stores the meter's latest cumulative index (m³) per day; daily consumption is
derived as an index diff at read time (see rules.build_water_panel). The
water_samples table keeps the same index per 30-min slot for the intraday
litre profiles.
"""
from datetime import datetime, timedelta

from app.module.db import transaction
from app.module.slots import SLOTS_PER_DAY, slot_index
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_water + water_samples tables (idempotent)."""
    with transaction() as conn:
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


def get_cached_water(start: str, end: str) -> list[dict]:
    with transaction() as conn:
        cur = conn.execute(
            "SELECT date, index_m3 FROM daily_water WHERE date >= ? AND date < ? ORDER BY date",
            (start, end),
        )
        return [{"date": r[0], "index_m3": r[1]} for r in cur.fetchall()]


def upsert_water(date: str, index_m3: float):
    now = datetime.now(PARIS_TZ).isoformat()
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_water (date, index_m3, fetched_at) VALUES (?, ?, ?)",
            (date, index_m3, now),
        )


def insert_water_sample(ts: str, index_m3: float):
    """Persist the slot's latest cumulative index (ts = 30-min slot start, ISO
    local). INSERT OR REPLACE keeps the last reading of the slot."""
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO water_samples (ts, index_m3) VALUES (?, ?)",
            (ts, index_m3),
        )


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
    with transaction() as conn:
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
                    profiles.setdefault(ts[:10], [None] * SLOTS_PER_DAY)[slot_index(dt)] = round(delta * 1000, 1)
            prev_index = index_m3
        return profiles
