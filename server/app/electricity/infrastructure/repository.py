"""Electricity domain repository — the only place that touches daily_consumption.

Owns the schema (with the talon migrations), the cached-days accessors and the
freshness check that gates the Conso API fetch.
"""
from datetime import datetime, timedelta

from app.module.db import connect
from app.system.config import PARIS_TZ


def init_schema():
    """Create the daily_consumption table (idempotent) + talon migrations."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_consumption (
            date TEXT PRIMARY KEY,
            hc_kwh REAL NOT NULL,
            hp_kwh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    # Migration: the talon (daily P5 power, W) was added later — add the column
    # to existing databases. Backfilled by fetch_and_cache on the next refresh.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_consumption)")]
    if "talon_w" not in cols:
        conn.execute("ALTER TABLE daily_consumption ADD COLUMN talon_w REAL")
    # Migration v1: the talon switched from a 24h percentile to a night-only one
    # (solar no longer crushes it). Old cached talons are stale — NULL them once
    # so fetch_and_cache re-fetches the load curve and recomputes them night-only.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        conn.execute("UPDATE daily_consumption SET talon_w = NULL")
        conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def get_cached_days(start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, hc_kwh, hp_kwh, talon_w FROM daily_consumption WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "hc_kwh": r[1], "hp_kwh": r[2], "talon_w": r[3]} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_days(days: list[dict]):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    for d in days:
        conn.execute(
            "INSERT OR REPLACE INTO daily_consumption (date, hc_kwh, hp_kwh, talon_w, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (d["date"], d["hc_kwh"], d["hp_kwh"], d.get("talon_w"), now),
        )
    conn.commit()
    conn.close()


def needs_refresh(start: str, end: str) -> bool:
    cached = get_cached_days(start, end)
    cached_dates = {d["date"] for d in cached}
    now = datetime.now(PARIS_TZ)

    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current < end_dt:
        ds = current.strftime("%Y-%m-%d")
        if ds not in cached_dates:
            return True
        current += timedelta(days=1)

    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if yesterday in cached_dates:
        conn = connect()
        cur = conn.execute(
            "SELECT fetched_at FROM daily_consumption WHERE date = ?", (yesterday,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            fetched = datetime.fromisoformat(row[0])
            if fetched.astimezone(PARIS_TZ).date() < now.date():
                return True
            if fetched.astimezone(PARIS_TZ).hour < 10:
                return True

    return False
