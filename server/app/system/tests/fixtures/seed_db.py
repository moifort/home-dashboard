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

from app import electricity, plants, solar, water
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
    """40+ complete days ending *yesterday*, plus today's partial row (the ZLinky
    integrates live since midnight, rendered as the chart's 'Auj.' bar)."""
    start = TODAY - timedelta(days=_SEED_DAYS)
    end = TODAY - timedelta(days=1)
    rows = []
    for i, d in enumerate(_daterange(start, end)):
        hc = round(2.8 + (i % 5) * 0.35 + (i % 2) * 0.25, 2)
        hp = round(3.6 + (i % 7) * 0.40 + (i % 3) * 0.30, 2)
        talon = round(305 + (i % 6) * 7 - (i % 4) * 3)
        rows.append((d.strftime("%Y-%m-%d"), hc, hp, float(talon), _FETCHED_AT))
    # Mid-afternoon partial day (FIXED_NOW is 14:30): deliberately small values.
    rows.append((TODAY.strftime("%Y-%m-%d"), 1.9, 2.3, 312.0, _FETCHED_AT))
    return rows


def _tic_sample_rows():
    """30-min mean-PAPP samples over the chart's 9 shown days — the intraday
    strip's source. A synthetic daily curve: night talon, morning / midday /
    evening bumps, all varying per (day, slot). One shown day stays sample-less
    (empty strip), another has a 2h slot gap, and today is partial (slots up to
    FIXED_NOW's 14:00 slot only). The index columns stay NULL (never read by
    the build path)."""
    rows = []
    start = TODAY - timedelta(days=8)
    for i, d in enumerate(_daterange(start, TODAY)):
        if i == 2:  # a shown day with no TIC sample at all → empty strip
            continue
        last_slot = 29 if d == TODAY else 48  # partial today: through 14:00
        for slot in range(last_slot):
            if i == 5 and 20 <= slot < 24:  # a 2h gap on one day
                continue
            hour = slot // 2
            base = 280.0 + (i % 5) * 12
            if 7 <= hour < 9:
                papp = base + 1500 + (slot % 3) * 250
            elif 12 <= hour < 14:
                papp = base + 800 + (slot % 2) * 300
            elif 19 <= hour < 22:
                papp = base + 2000 + (slot % 4) * 200
            else:
                papp = base + (slot % 4) * 30
            ts = datetime(d.year, d.month, d.day, hour, (slot % 2) * 30).isoformat()
            rows.append((ts, None, None, round(papp, 1)))
    return rows


def _solar_sample_rows():
    """30-min mean-PV samples over the chart's 9 shown days — the Solaire
    intraday strip's source. A deterministic daylight bell (peak ~13h30, kept
    under the 800 W inverter cap), 0 W at night (the inverter heartbeats
    through the night). Mirrors the TIC seeding quirks: one shown day is
    sample-less, another has a 2h gap, and today is partial (through 14:00)."""
    rows = []
    start = TODAY - timedelta(days=8)
    for i, d in enumerate(_daterange(start, TODAY)):
        if i == 2:  # a shown day with no sample at all → empty strip
            continue
        last_slot = 29 if d == TODAY else 48  # partial today: through 14:00
        for slot in range(last_slot):
            if i == 5 and 20 <= slot < 24:  # a 2h gap on one day
                continue
            pv = max(0.0, 760 - abs(slot - 27) * 55 - (i % 4) * 40 - (slot % 3) * 12)
            ts = datetime(d.year, d.month, d.day, slot // 2, (slot % 2) * 30).isoformat()
            rows.append((ts, round(pv, 1)))
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


def _plant_rows():
    """Daily soil-sensor readings (the day's latest of each metric) for two
    plants over the spark window, including today (the on-screen current value).
    Ficus reports every day; Basilic skips two early days to exercise the spark's
    gap. battery_state is only meaningful on today's live row (NULL on history):
    Ficus "low" → red battery icon, Basilic "middle" → none. The water drop is
    driven elsewhere (today's moisture vs the 50% threshold in conftest): Ficus
    45 < 50 → drop, Basilic 61 ≥ 50 → none. Values are deterministic per (plant,
    day index)."""
    start = TODAY - timedelta(days=9)
    rows = []
    for i, d in enumerate(_daterange(start, TODAY)):
        ds = d.strftime("%Y-%m-%d")
        today = d == TODAY
        rows.append(("ficus", ds, float(30 + (i % 6) * 5), 20.0 + (i % 3),
                     800.0 + (i % 4) * 150, 18.0 + (i % 5),
                     "low" if today else None, _FETCHED_AT))
        if i not in (1, 4):  # two missing days early -> a gap in Basilic's spark
            rows.append(("basilic", ds, float(45 + (i % 5) * 4), 22.0 + (i % 2),
                         600.0 + (i % 3) * 200, 22.0 + (i % 4),
                         "middle" if today else None, _FETCHED_AT))
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


def _water_sample_rows():
    """Per-slot cumulative index (m³) over the 9 shown days plus the day
    before (midnight baseline for the first day's deltas) — the Eau intraday
    strip's source. Usage follows a deterministic morning / midday / evening
    pattern (litres per 30-min slot); the meter reports every slot, so quiet
    slots read as 0 L. Mirrors the TIC seeding quirks: one shown day is
    sample-less (its litres land on the next reporting day), another has a 2h
    gap, and today is partial (through 14:00)."""
    rows = []
    start = TODAY - timedelta(days=9)
    index_m3 = 2000.0
    for i, d in enumerate(_daterange(start, TODAY)):
        if i == 3:  # shown day 2 with no sample at all → empty strip
            index_m3 += 0.150  # the meter still runs; the jump lands on the next day
            continue
        last_slot = 29 if d == TODAY else 48  # partial today: through 14:00
        for slot in range(last_slot):
            if i == 6 and 20 <= slot < 24:  # a 2h gap on shown day 5
                continue
            hour = slot // 2
            if 7 <= hour < 9:
                litres = 9 + (slot % 3) * 3 + (i % 4)
            elif 12 <= hour < 14:
                litres = 4 + (slot % 2) * 3
            elif 19 <= hour < 22:
                litres = 11 + (slot % 4) * 2 + (i % 3) * 2
            else:
                litres = 0
            index_m3 += litres / 1000.0
            ts = datetime(d.year, d.month, d.day, hour, (slot % 2) * 30).isoformat()
            rows.append((ts, round(index_m3, 4)))
    return rows


def seed():
    """Create every schema and insert the deterministic rows. Assumes
    `app.module.db.DB_PATH` already points at the (empty) target file."""
    electricity.init_schema()
    solar.init_schema()
    power.init_schema()
    water.init_schema()
    plants.init_schema()

    conn = db.connect()
    conn.executemany(
        "INSERT OR REPLACE INTO daily_consumption "
        "(date, hc_kwh, hp_kwh, talon_w, fetched_at) VALUES (?, ?, ?, ?, ?)",
        _consumption_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO tic_samples (ts, hchc_kwh, hchp_kwh, papp_va) VALUES (?, ?, ?, ?)",
        _tic_sample_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_production (date, pv_wh, fetched_at) VALUES (?, ?, ?)",
        _production_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO solar_samples (ts, pv_w) VALUES (?, ?)",
        _solar_sample_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_power (slug, date, cons_wh, hc_wh, fetched_at) VALUES (?, ?, ?, ?, ?)",
        _power_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_water (date, index_m3, fetched_at) VALUES (?, ?, ?)",
        _water_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO water_samples (ts, index_m3) VALUES (?, ?)",
        _water_sample_rows(),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO daily_plants "
        "(slug, date, moisture, temperature, illuminance, fertility, "
        "battery_state, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        _plant_rows(),
    )
    conn.commit()
    conn.close()
