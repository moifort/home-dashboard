"""Solar domain repository — the only place that touches daily_production.

The PowerStream exposes only instantaneous PV watts (no energy counter), so the
command side integrates the heartbeat power into daily Wh and persists it here.
"""
from datetime import datetime

from app.module.db import connect
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_production table (idempotent)."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_production (
            date TEXT PRIMARY KEY,
            pv_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def get_cached_production(start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, pv_wh FROM daily_production WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "pv_kwh": round(r[1] / 1000, 2)} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_production(date: str, pv_wh: float):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_production (date, pv_wh, fetched_at) VALUES (?, ?, ?)",
        (date, pv_wh, now),
    )
    conn.commit()
    conn.close()
