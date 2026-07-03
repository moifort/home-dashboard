"""Water domain business rules — pure derivations from the meter index history.

The wM-Bus meter reports a *cumulative* index (m³), not a power, so — unlike the
Cumulus contactor — daily consumption is a *difference of index* between days
(like the Linky index), never a time integration.
"""
from datetime import datetime, timedelta

from app.system.config import DAYS_FR

CHART_DAYS = 9  # daily bars shown in the dedicated water chart


def _index_asof(rows: list[dict], day: str) -> float | None:
    """Latest cumulative index recorded on or before `day` (carry-forward), or
    None when no reading exists that early yet."""
    found = None
    for r in rows:
        if r["date"] <= day:
            found = r["index_m3"]
        else:
            break
    return found


def fetch_window(now: datetime) -> tuple[str, str]:
    """The (start, end) date range to read so the chart, its trend baseline and
    the month-to-date total are all covered. +1 day for the diff against the day
    before the oldest shown."""
    today = now.date()
    first_of_month = today.replace(day=1)
    start = min(today - timedelta(days=2 * CHART_DAYS + 1), first_of_month - timedelta(days=2))
    end_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    return start.strftime("%Y-%m-%d"), end_str


def build_water_panel(rows: list[dict], now: datetime, price_m3: float,
                      litre_profiles: dict | None = None) -> dict:
    """Build the water chart + stats from the meter's index history.

    Daily litres are index diffs between consecutive days (carry-forward across
    days with no frame, so the jump lands on the next day that reports). History
    starts at first connection (no backfill).

    `litre_profiles` maps a date to its 48-slot intraday litres profile
    (None-padded); each shown day carries its profile as `intraday` for the
    mini graph under its bar (None when the date has no sample).
    """
    today = now.date()
    first_of_month = today.replace(day=1)

    # No reading recorded yet today → today's bar is N/A, not a carry-forward 0
    # (otherwise the diff against yesterday's carried-forward index reads as zero).
    today_str = today.strftime("%Y-%m-%d")
    has_today_reading = any(r["date"] == today_str for r in rows)

    # Per-day litres for the last 2*CHART_DAYS days (last CHART_DAYS shown; the
    # CHART_DAYS before feed the trend baseline).
    daily = []  # list of (date, litres|None) oldest->newest
    for i in range(2 * CHART_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        prev_str = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        idx_d = _index_asof(rows, d_str)
        idx_prev = _index_asof(rows, prev_str)
        if idx_d is None or idx_prev is None or (i == 0 and not has_today_reading):
            litres = None
        else:
            litres = max(0.0, (idx_d - idx_prev) * 1000)
        daily.append((d, litres))

    shown = daily[-CHART_DAYS:]
    water_days = [
        {"day": DAYS_FR[d.weekday()], "date": d.strftime("%Y-%m-%d"),
         "liters": litres, "today": d == today,
         "intraday": (litre_profiles or {}).get(d.strftime("%Y-%m-%d"))}
        for d, litres in shown
    ]

    def avg(seq):
        vals = [v for v in seq if v is not None]
        return sum(vals) / len(vals) if vals else None

    avg_recent = avg(v for _, v in daily[-CHART_DAYS:])
    avg_prev = avg(v for _, v in daily[-2 * CHART_DAYS:-CHART_DAYS])
    trend_pct = round((avg_recent - avg_prev) / avg_prev * 100) if avg_recent and avg_prev else 0

    # Month-to-date volume: index now minus the index at the end of last month.
    idx_now = _index_asof(rows, today.strftime("%Y-%m-%d"))
    idx_month_start = _index_asof(rows, (first_of_month - timedelta(days=1)).strftime("%Y-%m-%d"))
    if idx_now is not None and idx_month_start is not None:
        month_total_m3 = max(0.0, idx_now - idx_month_start)
    else:
        month_total_m3 = None

    water_stats = {
        "avg_text": f"{avg_recent:.0f}" if avg_recent is not None else "N/A",
        "avg_l": round(avg_recent, 1) if avg_recent is not None else None,  # numeric, for the chart's average line
        "avg_pct": trend_pct,
        "month_total_text": f"{month_total_m3:.2f}" if month_total_m3 is not None else "N/A",
        "cost_text": f"{month_total_m3 * price_m3:.2f}"
        if (month_total_m3 is not None and price_m3 > 0) else None,
    }
    return {"water_days": water_days, "water_stats": water_stats}
