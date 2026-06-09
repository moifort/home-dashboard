"""Electricity domain repository — the only place that touches daily_consumption
and tic_samples.

Owns the schema (with the talon migrations), the daily accessors used by the
render path and the 30-min TIC samples written by the ZLinky integrator.
"""
from datetime import datetime

from app.module.db import connect
from app.system.config import PARIS_TZ

from app.electricity.infrastructure.linky_client import (
    TALON_NIGHT_END,
    TALON_NIGHT_START,
)


def init_schema():
    """Create the tables (idempotent) + talon migrations."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_consumption (
            date TEXT PRIMARY KEY,
            hc_kwh REAL NOT NULL,
            hp_kwh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    # Migration: the talon (daily night-percentile power, W) was added later —
    # add the column to existing databases. Refilled by the integrator going forward.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_consumption)")]
    if "talon_w" not in cols:
        conn.execute("ALTER TABLE daily_consumption ADD COLUMN talon_w REAL")
    # Migration v1: the talon switched from a 24h percentile to a night-only one
    # (solar no longer crushes it). Old cached talons are stale — NULL them once.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        conn.execute("UPDATE daily_consumption SET talon_w = NULL")
        conn.execute("PRAGMA user_version = 1")
    # 30-min TIC samples (ZLinky): index snapshots + mean apparent power per
    # slot. Unlimited retention (~17k rows/year) — the fine-grained history the
    # daily aggregate is derived from, and the talon's night sample source.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tic_samples (
            ts TEXT PRIMARY KEY,
            hchc_kwh REAL,
            hchp_kwh REAL,
            papp_va REAL
        )"""
    )
    # Persisted tariff windows so the Home panel survives a restart/redeploy
    # (otherwise the live-PTEC windows live in RAM only and blank out for ~24h).
    # One row per window — a day has two HC + two HP windows — plus the open
    # (in-progress) window with a NULL end. Reloaded on startup, rewritten at each
    # PTEC transition.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tariff_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT
        )"""
    )
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


def upsert_day(date: str, hc_kwh: float, hp_kwh: float, talon_w):
    """Single-day upsert — the integrator's 30s persist."""
    now = datetime.now(PARIS_TZ).isoformat()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO daily_consumption (date, hc_kwh, hp_kwh, talon_w, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (date, hc_kwh, hp_kwh, talon_w, now),
    )
    conn.commit()
    conn.close()


def insert_sample(ts: str, hchc_kwh: float, hchp_kwh: float, papp_va: float | None):
    """Persist one 30-min TIC slot (ts = slot start, ISO local)."""
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO tic_samples (ts, hchc_kwh, hchp_kwh, papp_va) VALUES (?, ?, ?, ?)",
        (ts, hchc_kwh, hchp_kwh, papp_va),
    )
    conn.commit()
    conn.close()


def get_papp_profiles(start: str, end: str) -> dict[str, list]:
    """Per-date intraday power profile: 48 half-hour slots of mean PAPP
    (W-ish VA), None where the slot has no sample. Only dates with at least
    one sample are returned — feeds the mini intraday graph under each EDF bar.
    """
    conn = connect()
    cur = conn.execute(
        "SELECT ts, papp_va FROM tic_samples WHERE ts >= ? AND ts < ? AND papp_va IS NOT NULL ORDER BY ts",
        (start, end),
    )
    profiles: dict[str, list] = {}
    for ts, papp in cur.fetchall():
        dt = datetime.fromisoformat(ts)
        slot = dt.hour * 2 + (1 if dt.minute >= 30 else 0)
        profiles.setdefault(ts[:10], [None] * 48)[slot] = papp
    conn.close()
    return profiles


def save_tariff_windows(open_window, windows: dict):
    """Replace the persisted tariff state: every completed window (end set) for
    each period plus the open (in-progress) window with a NULL end. `windows` is
    {"HC": [(start, end), ...], "HP": [...]} of datetimes; `open_window` is
    (period, start) or None. Insertion order is HC then HP then open, preserved on
    reload via the autoincrement id."""
    conn = connect()
    conn.execute("DELETE FROM tariff_windows")
    for period in ("HC", "HP"):
        for start, end in windows.get(period, []):
            conn.execute(
                "INSERT INTO tariff_windows (period, start, end) VALUES (?, ?, ?)",
                (period, start.isoformat(), end.isoformat()),
            )
    if open_window is not None:
        period, start = open_window
        conn.execute(
            "INSERT INTO tariff_windows (period, start, end) VALUES (?, ?, NULL)",
            (period, start.isoformat()),
        )
    conn.commit()
    conn.close()


def load_tariff_windows():
    """Reload the persisted tariff state, chronological per period. Returns
    (windows, open_window): windows = {"HC": [(start, end), ...], "HP": [...]} of
    datetimes (rows with a non-NULL end), open_window = (period, start) for the
    single NULL-end row, or None."""
    conn = connect()
    cur = conn.execute("SELECT period, start, end FROM tariff_windows ORDER BY id")
    windows = {"HC": [], "HP": []}
    open_window = None
    for period, start, end in cur.fetchall():
        if end is None:
            open_window = (period, datetime.fromisoformat(start))
        else:
            windows.setdefault(period, []).append(
                (datetime.fromisoformat(start), datetime.fromisoformat(end))
            )
    conn.close()
    return windows, open_window


def get_night_papp(date: str) -> list[float]:
    """The date's night-window mean PAPP samples (W-ish VA), for the talon.

    Night = slot hour >= TALON_NIGHT_START or < TALON_NIGHT_END, on the slot's
    own date — the same sample-date grouping the REST load curve had.
    """
    conn = connect()
    cur = conn.execute(
        "SELECT ts, papp_va FROM tic_samples WHERE ts >= ? AND ts < ? AND papp_va IS NOT NULL ORDER BY ts",
        (date, f"{date}T24"),
    )
    samples = []
    for ts, papp in cur.fetchall():
        hour = datetime.fromisoformat(ts).hour
        if hour >= TALON_NIGHT_START or hour < TALON_NIGHT_END:
            samples.append(papp)
    conn.close()
    return samples
