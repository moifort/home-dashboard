"""Power sub-domain repository — the only place that touches daily_power.

One shared table keyed by (slug, date) for every configured power sensor; the
init also performs the one-time copy of the legacy single-device tables.
"""
import logging
from datetime import datetime

from app.module.db import connect
from app.system.config import PARIS_TZ

logger = logging.getLogger(__name__)

# Legacy single-device tables migrated into the shared daily_power table once.
# The target slugs match _slugify() of the recommended display names, so history
# re-attaches as long as those names are kept in POWER_SENSORS.
_LEGACY_TABLES = (("daily_cumulus", "cumulus"), ("daily_washer", "lave-linge"))


def init_schema():
    """Create the shared daily_power table and migrate legacy tables once."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_power (
            slug TEXT NOT NULL,
            date TEXT NOT NULL,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (slug, date)
        )"""
    )
    # Off-peak share of the day's Wh (idempotent migration, mirrors talon_w).
    # NULL = unknown: days integrated before this column existed stay excluded
    # from the HC% computation rather than counting as 0% off-peak.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_power)")}
    if "hc_wh" not in cols:
        conn.execute("ALTER TABLE daily_power ADD COLUMN hc_wh REAL")
    for table, slug in _LEGACY_TABLES:
        _migrate_legacy(conn, table, slug)
    conn.commit()
    conn.close()


def _migrate_legacy(conn, table: str, slug: str):
    """One-time copy of a legacy single-device table into daily_power[slug].

    Idempotent: skips if the table is gone or daily_power already holds the slug.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return
    already = conn.execute(
        "SELECT 1 FROM daily_power WHERE slug=? LIMIT 1", (slug,)
    ).fetchone()
    if already:
        return
    rows = conn.execute(f"SELECT date, cons_wh, fetched_at FROM {table}").fetchall()
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO daily_power (slug, date, cons_wh, fetched_at) VALUES (?, ?, ?, ?)",
        [(slug, d, wh, at) for d, wh, at in rows],
    )
    logger.info("Migrated %d rows from %s into daily_power[%s]", len(rows), table, slug)


def get_cached_power(slug: str, start: str, end: str) -> list[dict]:
    conn = connect()
    cur = conn.execute(
        "SELECT date, cons_wh, hc_wh FROM daily_power "
        "WHERE slug = ? AND date >= ? AND date < ? ORDER BY date",
        (slug, start, end),
    )
    rows = [{"date": r[0], "cons_kwh": round(r[1] / 1000, 2),
             "hc_kwh": round(r[2] / 1000, 2) if r[2] is not None else None}
            for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_power(slug: str, date: str, cons_wh: float, hc_wh: float | None = None):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_power (slug, date, cons_wh, hc_wh, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (slug, date, cons_wh, hc_wh, now),
    )
    conn.commit()
    conn.close()
