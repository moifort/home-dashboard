"""Seed a deterministic SQLite database for the golden tests.

Fills every daily table the render pipeline reads (consumption, production,
power sensors, water) with **fixed, reproducible** rows relative to a frozen "today".
Values come from pure index-based patterns (no randomness, no clock) so the same
seed always yields the same `data` dict and the same rendered buffer.

The caller must point `app.module.db.DB_PATH` at the target file *before* calling
`seed()` (the conftest `seeded_db` fixture does this), since every `init_schema()`
and `connect()` reads that module global.
"""
from datetime import date, datetime, timedelta

from app import electricity, solar, water
from app.electricity import power
from app.module import db
from app.system.config import PARIS_TZ

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


# A "Salon" group of two plugs summed into one bottom-table row. prise-2 joins
# halfway through the window, so early days are prise-1 only — this exercises the
# "a day with at least one member is summed over the present members" rule.
SALON_1_SLUG = "salon-zigbee2mqtt-prise-1"
SALON_2_SLUG = "salon-zigbee2mqtt-prise-2"


def _power_rows():
    """Daily power-sensor Wh ending yesterday (integrated, no same-day flush
    needed). Two lone sensors (cumulus/washer) mirror the old value patterns so
    those rows stay stable; a two-topic `Salon` group seeds the summation path.
    hc_wh is a deterministic per-day fraction of cons_wh; the oldest days stay
    NULL (pre-deployment history) to exercise the "unknown days excluded" rule."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    end = TODAY - timedelta(days=1)
    rows = []
    for i, d in enumerate(_daterange(start, end)):
        ds = d.strftime("%Y-%m-%d")

        def _hc(cons_wh, j=i):
            # NULL before the HC split existed; then 30..60% varying per day.
            if j < _SEED_DAYS // 4:
                return None
            return round(cons_wh * (0.3 + (j % 4) * 0.1), 1)

        cumulus_wh = round((1.4 + (i % 4) * 0.5 + (i % 3) * 0.3) * 1000, 1)
        washer_wh = round((0.5 + (i % 3) * 0.2 + (i % 5) * 0.15) * 1000, 1)
        rows.append(("cumulus", ds, cumulus_wh, _hc(cumulus_wh), _FETCHED_AT))
        # The washer drifts out of the off-peak hours over the last 9 days
        # (70% -> 25% HC), so the golden exercises the prise_hc_drop alert.
        washer_hc = None if i < _SEED_DAYS // 4 else round(
            washer_wh * (0.7 if i < _SEED_DAYS - 9 else 0.25), 1)
        rows.append(("lave-linge", ds, washer_wh, washer_hc, _FETCHED_AT))
        salon1_wh = round((0.8 + (i % 3) * 0.3) * 1000, 1)
        rows.append((SALON_1_SLUG, ds, salon1_wh, _hc(salon1_wh), _FETCHED_AT))
        if i >= _SEED_DAYS // 2:  # prise-2 joins partway through
            salon2_wh = round((0.6 + (i % 4) * 0.25) * 1000, 1)
            rows.append((SALON_2_SLUG, ds, salon2_wh, _hc(salon2_wh), _FETCHED_AT))
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
    `app.module.db.DB_PATH` already points at the (empty) target file."""
    electricity.init_schema()
    solar.init_schema()
    power.init_schema()
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
        "INSERT OR REPLACE INTO daily_power (slug, date, cons_wh, hc_wh, fetched_at) VALUES (?, ?, ?, ?, ?)",
        _power_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_water (date, index_m3, fetched_at) VALUES (?, ?, ?)",
        _water_rows(),
    )
    conn.commit()
    conn.close()
