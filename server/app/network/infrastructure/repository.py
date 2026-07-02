"""Network domain repository — the only place that touches daily_unifi.

A tiny daily snapshot table feeds the ▲▼ trends (one row/day, last refresh wins;
no backfill — history starts at first connection).
"""
from datetime import datetime

from app.module.db import transaction
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_unifi snapshot table (idempotent)."""
    with transaction() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_unifi (
                date TEXT PRIMARY KEY,
                usage_bytes REAL,
                speed_dl REAL,
                latency_ms REAL,
                isp_pct REAL,
                wifi_pct REAL,
                fetched_at TEXT NOT NULL
            )"""
        )


def upsert_snapshot(snap: dict):
    """Store today's reading (one row/day; last refresh of the day wins)."""
    today = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")
    now = datetime.now(PARIS_TZ).isoformat()
    with transaction() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_unifi
               (date, usage_bytes, latency_ms, isp_pct, wifi_pct, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (today, snap.get("usage_bytes"), snap.get("latency_ms"),
             snap.get("isp_pct"), snap.get("wifi_pct"), now),
        )


def trend_values(column: str, limit: int) -> list:
    """Up to `limit` most recent values of `column` from days before today,
    newest first (column is a fixed internal name, never user input)."""
    today = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")
    with transaction() as conn:
        cur = conn.execute(
            f"SELECT {column} FROM daily_unifi "
            f"WHERE date < ? AND {column} IS NOT NULL ORDER BY date DESC LIMIT ?",
            (today, limit),
        )
        return [r[0] for r in cur.fetchall()]
