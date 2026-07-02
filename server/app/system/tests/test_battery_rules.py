"""Unit tests for the battery autonomy rules (battery/rules.py).

The charge-% estimate calibrates on the longest completed cycle (≈ a full
charge). A USB power blip or a re-flash also reports POWERON and manufactures a
minutes-long "cycle"; these spurious runs must not pollute the average nor
become the 100 % reference.
"""
from datetime import datetime, timedelta

from app.battery.rules import build_battery_view

NOW = datetime(2026, 6, 2, 12, 0)


def _cycle(start: datetime, end: datetime | None) -> dict:
    return {"started_at": start.isoformat(),
            "ended_at": (end or start).isoformat()}


def test_short_blip_cycle_excluded_from_stats():
    """A 3h POWERON-blip run among 4-day runs affects neither avg nor record."""
    t0 = NOW - timedelta(days=10)
    cycles = [
        _cycle(t0, t0 + timedelta(days=4)),                       # real run
        _cycle(t0 + timedelta(days=4), t0 + timedelta(days=4, hours=3)),  # blip
        _cycle(t0 + timedelta(days=4, hours=3), t0 + timedelta(days=8, hours=3)),  # real run
        _cycle(NOW - timedelta(days=2), None),                    # current run
    ]
    view = build_battery_view(cycles, NOW)
    assert view["cycles"] == 2          # the blip is not counted
    assert view["avg_text"] == "4j"     # 3h blip would have dragged this down
    assert view["record_text"] == "4j"
    assert view["percent"] == 50        # 2 days into a 4-day record


def test_all_short_cycles_yield_no_estimate():
    """Only spurious completed runs → same behavior as no completed cycles."""
    t0 = NOW - timedelta(days=1)
    cycles = [
        _cycle(t0, t0 + timedelta(hours=2)),
        _cycle(t0 + timedelta(hours=2), t0 + timedelta(hours=5)),
        _cycle(NOW - timedelta(hours=6), None),
    ]
    view = build_battery_view(cycles, NOW)
    assert view["percent"] is None
    assert view["avg_text"] is None
    assert view["record_text"] is None
    assert view["cycles"] == 0
    assert view["since_text"] == "6h"   # the current-run figure still works
