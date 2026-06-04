"""Water domain repository — the only place that touches the daily_water table.

Stores the meter's latest cumulative index (m³) per day; daily consumption is
derived as an index diff at read time (see rules.build_water_panel).
"""
from datetime import datetime

from app.module.db import connect
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_water table (idempotent)."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_water (
            date TEXT PRIMARY KEY,
            index_m3 REAL NOT NULL,
            fetched_at TEXT NOT NULL
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
