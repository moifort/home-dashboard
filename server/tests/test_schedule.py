"""Unit tests for the screen-refresh schedule helpers.

Focus: `next_screen_wake` must mirror the firmware's skip guard
(`sleep_min < SCREEN_WAKE_SKIP_MIN` → += interval in computeSleepUs), so the
Home panel's "next refresh" matches the device's real next wake even when clock
drift wakes the ESP a minute before a boundary.
"""
from datetime import datetime

from app.schedule import next_screen_refresh, next_screen_wake


def _at(h, m):
    return datetime(2026, 6, 3, h, m)


# Default schedule: interval 120 min, skip window 5 min.

def test_wake_well_before_boundary_is_the_boundary():
    assert next_screen_wake(_at(9, 30)) == _at(10, 0)


def test_wake_at_skip_threshold_keeps_the_boundary():
    # 5 min away is NOT < 5 → the firmware still sleeps to 10:00.
    assert next_screen_wake(_at(9, 55)) == _at(10, 0)


def test_wake_inside_skip_window_skips_to_next_interval():
    # 4 min away (< 5) → firmware skips 10:00, next real wake is 12:00.
    assert next_screen_wake(_at(9, 56)) == _at(12, 0)


def test_wake_one_minute_before_boundary_skips():
    # The reported bug: woke 09:59, panel must show 12:00, not 10:00.
    assert next_screen_wake(_at(9, 59)) == _at(12, 0)
    # Contrast with the raw boundary helper, which (correctly) returns 10:00.
    assert next_screen_refresh(_at(9, 59)) == _at(10, 0)


def test_wake_exactly_on_boundary_targets_next_interval():
    assert next_screen_wake(_at(10, 0)) == _at(12, 0)
