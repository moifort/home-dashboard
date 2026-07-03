"""Network domain repository — the only place that touches the network tables.

daily_unifi is a tiny daily snapshot feeding the ▲▼ trends (one row/day, last
refresh wins; no backfill — history starts at first connection). known_clients
remembers every client MAC ever seen, backing the "new device" alert.
"""
from datetime import datetime, timedelta

from app.module.db import transaction
from app.system.config import PARIS_TZ

NEW_CLIENT_WINDOW_H = 24  # a client first seen within this window reads as "new"


def init_schema():
    """Create the daily_unifi snapshot + known_clients tables (idempotent)."""
    with transaction() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_unifi (
                date TEXT PRIMARY KEY,
                usage_bytes REAL,
                speed_dl REAL,      -- vestigial: never written nor read
                latency_ms REAL,
                isp_pct REAL,
                wifi_pct REAL,
                fetched_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS known_clients (
                mac TEXT PRIMARY KEY,
                name TEXT,
                first_seen TEXT  -- NULL = present at the feature's first run (never alerts)
            )"""
        )


def register_clients(clients: list[tuple[str, str]]) -> list[str]:
    """Upsert the currently connected (mac, name) pairs and return the names
    first seen within the last NEW_CLIENT_WINDOW_H hours, newest first.

    The very first run seeds the whole table silently (first_seen NULL) so a
    fresh deploy doesn't flag the entire home as new devices; from then on an
    unknown MAC is stamped with its discovery time and reads as "new" for the
    window. Names refresh on every pass (renames follow)."""
    now = datetime.now(PARIS_TZ)
    cutoff = (now - timedelta(hours=NEW_CLIENT_WINDOW_H)).isoformat()
    with transaction() as conn:
        empty = conn.execute("SELECT COUNT(*) FROM known_clients").fetchone()[0] == 0
        first_seen = None if empty else now.isoformat()
        for mac, name in clients:
            conn.execute(
                """INSERT INTO known_clients (mac, name, first_seen) VALUES (?, ?, ?)
                   ON CONFLICT(mac) DO UPDATE SET name = excluded.name""",
                (mac, name, first_seen),
            )
        cur = conn.execute(
            "SELECT name FROM known_clients WHERE first_seen >= ? ORDER BY first_seen DESC",
            (cutoff,),
        )
        return [r[0] for r in cur.fetchall()]


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
