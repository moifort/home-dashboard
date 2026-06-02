"""Seed a deterministic SQLite database for the golden tests.

Fills every daily table the render pipeline reads (consumption, production,
cumulus, water) with **fixed, reproducible** rows relative to a frozen "today".
Values come from pure index-based patterns (no randomness, no clock) so the same
seed always yields the same `data` dict and the same rendered buffer.

The caller must point `app.db.DB_PATH` at the target file *before* calling
`seed()` (the conftest `seeded_db` fixture does this), since every `init_schema()`
and `connect()` reads that module global.
"""
from datetime import date, datetime, timedelta

from app import db
from app.config import PARIS_TZ
from app.integrations import cumulus, ecoflow, linky, water

# Frozen reference instant for the whole test suite. Everything (seeded ranges,
# build_core's "today", each attach's date math) is computed relative to this.
FIXED_NOW = datetime(2026, 6, 2, 14, 30, 45, tzinfo=PARIS_TZ)
TODAY = FIXED_NOW.date()  # 2026-06-02 (a Tuesday)

# Fixed write timestamp for every row's fetched_at (never read by the build path,
# but kept constant so the DB file itself is reproducible).
_FETCHED_AT = FIXED_NOW.isoformat()

# How far back to seed. 40+ days covers every window: build_core needs 9 recent +
# 28 prior complete days, the solar/cumulus trends look back ~37 days, water ~19.
_SEED_DAYS = 44


def _daterange(start: date, end_inclusive: date):
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def _consumption_rows():
    """40+ complete days ending *yesterday* (Linky has no same-day data)."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    end = TODAY - timedelta(days=1)
    rows = []
    for i, d in enumerate(_daterange(start, end)):
        hc = round(2.8 + (i % 5) * 0.35 + (i % 2) * 0.25, 2)
        hp = round(3.6 + (i % 7) * 0.40 + (i % 3) * 0.30, 2)
        talon = round(305 + (i % 6) * 7 - (i % 4) * 3)
        rows.append((d.strftime("%Y-%m-%d"), hc, hp, float(talon), _FETCHED_AT))
    return rows


def _production_rows():
    """Daily PV Wh including today (a partial 'Auj.' bar). One 0-kWh day stays in
    the older history; today's value is deliberately small (mid-day partial)."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    pattern = [0.0, 5.2, 9.8, 14.2, 11.8, 7.4, 13.1, 2.6, 8.9]  # kWh
    rows = []
    for i, d in enumerate(_daterange(start, TODAY)):
        kwh = pattern[i % len(pattern)]
        if d == TODAY:
            kwh = 3.1  # partial day so far
        rows.append((d.strftime("%Y-%m-%d"), kwh * 1000, _FETCHED_AT))
    return rows


def _cumulus_rows():
    """Daily cumulus Wh ending yesterday (integrated, no same-day flush needed)."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    end = TODAY - timedelta(days=1)
    rows = []
    for i, d in enumerate(_daterange(start, end)):
        kwh = 1.4 + (i % 4) * 0.5 + (i % 3) * 0.3
        rows.append((d.strftime("%Y-%m-%d"), round(kwh * 1000, 1), _FETCHED_AT))
    return rows


def _water_rows():
    """Cumulative water index (m³) including today. Daily litres follow a fixed
    pattern; the index is their running sum from a fixed base."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    litres = [120, 142, 168, 95, 210, 130, 118, 155, 180, 102]
    rows = []
    index_m3 = 1000.0
    for i, d in enumerate(_daterange(start, TODAY)):
        index_m3 += litres[i % len(litres)] / 1000.0
        rows.append((d.strftime("%Y-%m-%d"), round(index_m3, 3), _FETCHED_AT))
    return rows


def seed():
    """Create every schema and insert the deterministic rows. Assumes
    `app.db.DB_PATH` already points at the (empty) target file."""
    linky.init_schema()
    ecoflow.init_schema()
    cumulus.init_schema()
    water.init_schema()

    conn = db.connect()
    conn.executemany(
        "INSERT OR REPLACE INTO daily_consumption "
        "(date, hc_kwh, hp_kwh, talon_w, fetched_at) VALUES (?, ?, ?, ?, ?)",
        _consumption_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_production (date, pv_wh, fetched_at) VALUES (?, ?, ?)",
        _production_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_cumulus (date, cons_wh, fetched_at) VALUES (?, ?, ?)",
        _cumulus_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_water (date, index_m3, fetched_at) VALUES (?, ?, ?)",
        _water_rows(),
    )
    conn.commit()
    conn.close()
