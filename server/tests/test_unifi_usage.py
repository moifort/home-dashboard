"""Unit tests for the UniFi data-usage windows + 30-vs-30 trend.

`_usage_from_daily` splits the daily WAN report into (yesterday, last-30-day
total, previous-30-day total); `_pct_change` turns the two 30-day windows into
the panel's usage trend. The date windowing is off-by-one-prone, so it is pinned
here with a fixed `today`.
"""
from datetime import date, datetime, timedelta

from app.config import PARIS_TZ
from app.integrations.unifi import _pct_change, _usage_from_daily

TODAY = date(2026, 6, 3)


def _row(day: date, value: int) -> dict:
    """One daily.gw row: noon-Paris timestamp (ms) so the date is unambiguous."""
    ts = int(datetime(day.year, day.month, day.day, 12, tzinfo=PARIS_TZ).timestamp() * 1000)
    return {"time": ts, "wan-tx_bytes": value, "wan-rx_bytes": 0}


def _report(per_day: dict) -> dict:
    return {"data": [_row(d, v) for d, v in per_day.items()]}


def test_windows_split_yesterday_last30_prev30():
    # last 30 days (-30..-1) each worth 10, previous 30 (-60..-31) each worth 5.
    per_day = {}
    for n in range(1, 31):
        per_day[TODAY - timedelta(days=n)] = 10
    for n in range(31, 61):
        per_day[TODAY - timedelta(days=n)] = 5
    y, last30, prev30 = _usage_from_daily(_report(per_day), today=TODAY)
    assert y == 10            # yesterday is in the last-30 window
    assert last30 == 30 * 10
    assert prev30 == 30 * 5
    assert _pct_change(last30, prev30) == 100.0  # twice as much → +100%


def test_today_and_out_of_range_days_excluded():
    per_day = {
        TODAY: 999,                       # today is incomplete → ignored
        TODAY - timedelta(days=61): 999,  # older than prev window → ignored
        TODAY - timedelta(days=1): 7,     # yesterday
    }
    y, last30, prev30 = _usage_from_daily(_report(per_day), today=TODAY)
    assert y == 7
    assert last30 == 7
    assert prev30 == 0


def test_no_baseline_gives_no_trend():
    # Only the last window has data (new install) → previous 30 days are 0.
    per_day = {TODAY - timedelta(days=n): 4 for n in range(1, 31)}
    _, last30, prev30 = _usage_from_daily(_report(per_day), today=TODAY)
    assert prev30 == 0
    assert _pct_change(last30, prev30) is None


def test_unavailable_report_is_none_safe():
    assert _usage_from_daily(None, today=TODAY) == (None, 0, 0)
    assert _usage_from_daily({}, today=TODAY) == (None, 0, 0)
