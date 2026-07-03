"""Solar domain repository — the only place that touches daily_production.

The PowerStream exposes only instantaneous PV watts (no energy counter), so the
command side integrates the heartbeat power into daily Wh and persists it here.
"""
from datetime import datetime

from app.module.db import transaction
from app.module.slots import SLOTS_PER_DAY, slot_index
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_production + solar_samples tables (idempotent)."""
    with transaction() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_production (
                date TEXT PRIMARY KEY,
                pv_wh REAL NOT NULL,
                fetched_at TEXT NOT NULL
            )"""
        )
        # One row per 30-min slot: the slot's mean PV watts, flushed at each slot
        # boundary (same technique as electricity's tic_samples). Unlimited
        # retention — feeds the mini intraday graph under each Solaire bar.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS solar_samples (
                ts TEXT PRIMARY KEY,
                pv_w REAL
            )"""
        )


def get_cached_production(start: str, end: str) -> list[dict]:
    with transaction() as conn:
        cur = conn.execute(
            "SELECT date, pv_wh FROM daily_production WHERE date >= ? AND date < ? ORDER BY date",
            (start, end),
        )
        return [{"date": r[0], "pv_kwh": round(r[1] / 1000, 2)} for r in cur.fetchall()]


def upsert_production(date: str, pv_wh: float):
    now = datetime.now(PARIS_TZ).isoformat()
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_production (date, pv_wh, fetched_at) VALUES (?, ?, ?)",
            (date, pv_wh, now),
        )


def insert_solar_sample(ts: str, pv_w: float):
    """Persist one 30-min slot's mean PV watts (ts = slot start, ISO local)."""
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO solar_samples (ts, pv_w) VALUES (?, ?)",
            (ts, pv_w),
        )


def get_pv_profiles(start: str, end: str) -> dict[str, list]:
    """Per-date intraday production profile: 48 half-hour slots of mean PV
    watts, None where the slot has no sample. Only dates with at least one
    sample are returned — feeds the mini intraday graph under each Solaire bar.
    """
    with transaction() as conn:
        cur = conn.execute(
            "SELECT ts, pv_w FROM solar_samples WHERE ts >= ? AND ts < ? AND pv_w IS NOT NULL ORDER BY ts",
            (start, end),
        )
        profiles: dict[str, list] = {}
        for ts, pv_w in cur.fetchall():
            dt = datetime.fromisoformat(ts)
            profiles.setdefault(ts[:10], [None] * SLOTS_PER_DAY)[slot_index(dt)] = pv_w
        return profiles
