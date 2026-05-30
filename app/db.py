"""SQLite storage layer.

Single place that opens the database (`connect()`), creates the schema and reads
/writes the daily tables. Timestamps use the Paris timezone for consistency with
the rest of the app.
"""
import os
import sqlite3
from datetime import datetime, timedelta

from app.config import DB_PATH, PARIS_TZ


def connect() -> sqlite3.Connection:
    """Open a connection to the configured database file."""
    return sqlite3.connect(DB_PATH)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_consumption (
            date TEXT PRIMARY KEY,
            hc_kwh REAL NOT NULL,
            hp_kwh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_production (
            date TEXT PRIMARY KEY,
            pv_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_cumulus (
            date TEXT PRIMARY KEY,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def get_cached_cumulus(start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, cons_wh FROM daily_cumulus WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "cons_kwh": round(r[1] / 1000, 2)} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_cumulus(date: str, cons_wh: float):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_cumulus (date, cons_wh, fetched_at) VALUES (?, ?, ?)",
        (date, cons_wh, now),
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


def get_cached_days(start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, hc_kwh, hp_kwh FROM daily_consumption WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "hc_kwh": r[1], "hp_kwh": r[2]} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_days(days: list[dict]):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    for d in days:
        conn.execute(
            "INSERT OR REPLACE INTO daily_consumption (date, hc_kwh, hp_kwh, fetched_at) VALUES (?, ?, ?, ?)",
            (d["date"], d["hc_kwh"], d["hp_kwh"], now),
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
