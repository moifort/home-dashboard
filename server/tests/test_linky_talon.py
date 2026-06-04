"""Unit tests for the night-only talon in `compute_daily_hc_hp`.

The Conso load curve is grid draw, net of self-consumed solar, so daytime samples
get crushed by PV injection. The talon must read the solar-free night window
(23h–05h) only, and P20 must skip the deepest night dip. These are pinned here on
a synthetic one-day load curve.
"""
from app.electricity.infrastructure.linky_client import (
    TALON_NIGHT_END,
    TALON_NIGHT_START,
    compute_daily_hc_hp,
)

NIGHT_FLOOR = 300   # stable standby at night
DAY_CRUSHED = 20    # daytime soutirage crushed below the floor by solar


def _is_night(hour: int) -> bool:
    return hour >= TALON_NIGHT_START or hour < TALON_NIGHT_END


def _day_curve(night_floor=NIGHT_FLOOR, day_watts=DAY_CRUSHED, night_dip=None):
    """48 half-hour samples for 2026-06-02. Night = floor (+ optional deep dip),
    daytime = a low solar-crushed value."""
    rows = []
    dip_done = False
    for h in range(24):
        for m in (0, 30):
            if _is_night(h):
                w = night_floor
                if night_dip is not None and not dip_done and h == 2 and m == 0:
                    w = night_dip
                    dip_done = True
            else:
                w = day_watts
            rows.append({"date": f"2026-06-02 {h:02d}:{m:02d}:00", "value": w})
    return rows


def test_talon_reads_night_floor_not_crushed_daytime():
    # Daytime is far below the night floor; a 24h percentile would pick ~day_watts.
    days = compute_daily_hc_hp(_day_curve())
    assert len(days) == 1
    assert days[0]["talon_w"] == NIGHT_FLOOR


def test_p20_skips_the_single_deep_night_dip():
    # One 50W night sample among eleven 300W ones must not become the talon.
    days = compute_daily_hc_hp(_day_curve(night_dip=50))
    assert days[0]["talon_w"] == NIGHT_FLOOR


def test_hc_hp_still_aggregate_the_full_day():
    # The night window only gates the talon, not the energy totals.
    days = compute_daily_hc_hp(_day_curve())
    assert days[0]["hc_kwh"] + days[0]["hp_kwh"] > 0


def test_day_without_night_samples_yields_none_talon():
    rows = [{"date": "2026-06-02 12:00:00", "value": 500}]  # midday only
    days = compute_daily_hc_hp(rows)
    assert days[0]["talon_w"] is None
