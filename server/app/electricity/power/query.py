"""Power sub-domain queries (read side): per-group stats + attach/status.

Topics sharing a display name are summed into one bottom-table row; every
figure here is computed over the group's per-topic daily series read from the
repository. SENSORS/ENABLED are read through the package at call time so tests
(and gen_preview) can monkeypatch them on `app.electricity.power`.
"""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.module.format import format_energy_kwh
from app.electricity.power.infrastructure import repository


def _merged_by_date(slugs: list, start: str, end: str) -> dict:
    """Sum each day's kWh across all of a group's topics over [start, end).

    A day present for at least one member appears in the result (sum of the
    present members); a day absent from every member is simply missing, so the
    caller's `.get(day)` yields `None` and the sparkline keeps its gap."""
    merged: dict = {}
    for slug in slugs:
        for r in repository.get_cached_power(slug, start, end):
            merged[r["date"]] = merged.get(r["date"], 0.0) + r["cons_kwh"]
    return merged


def _hc_pct(slugs: list, start: str, end: str):
    """% of the group's [start, end) consumption that fell in off-peak windows.

    Only days whose hc_wh is known (non-NULL) count — numerator and denominator
    stay on the same day set, so pre-deployment history (no HC split) is simply
    excluded. None when no day has HC info yet, or nothing was consumed."""
    cons_sum = 0.0
    hc_sum = 0.0
    have_hc = False
    for slug in slugs:
        for r in repository.get_cached_power(slug, start, end):
            if r["hc_kwh"] is None:
                continue
            have_hc = True
            cons_sum += r["cons_kwh"]
            hc_sum += r["hc_kwh"]
    if not have_hc or cons_sum <= 0:
        return None
    return round(hc_sum / cons_sum * 100)


def _group_spark(slugs: list, today, today_str: str) -> list:
    """The last 7 complete days' summed kWh (oldest→newest, ending yesterday),
    aligned with the EDF chart axis. `None` for any day no member reported."""
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    by_date = _merged_by_date(slugs, week_ago, today_str)
    return [by_date.get((today - timedelta(days=n)).strftime("%Y-%m-%d")) for n in range(7, 0, -1)]


def _group_stats(slugs: list, today, today_str: str) -> dict:
    """Yesterday's kWh, recent daily average and trend for one group (summed).

    Unlike the Linky data (whose API can return garbage), a plug's reading is
    trusted as-is — every recorded day counts toward the average (no near-zero
    floor), and small values render in Wh rather than collapsing to "0.0 kWh"."""
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    # None = no report at all yesterday (listener down, pre-install) — distinct
    # from a real 0 Wh day (device off but reporting), which renders "0 Wh".
    yesterday_kwh = _merged_by_date(slugs, yesterday_str, today_str).get(yesterday_str)

    # Yesterday's off-peak share of the group (None when no member carries the
    # HC split yet) — feeds the "heated on peak hours" alert.
    hc_vals = [r["hc_kwh"] for slug in slugs
               for r in repository.get_cached_power(slug, yesterday_str, today_str)
               if r["hc_kwh"] is not None]
    yesterday_hc_kwh = sum(hc_vals) if hc_vals else None

    past = list(_merged_by_date(slugs, nine_ago, today_str).values())
    avg = sum(past) / len(past) if past else 0.0

    # Trend: last 9 days vs the 28 days before them (mirrors the solar stats).
    prev_start = (today - timedelta(days=37)).strftime("%Y-%m-%d")
    prev = list(_merged_by_date(slugs, prev_start, nine_ago).values())
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100) if avg_prev > 0 else 0

    # "—" with the unit kept = the figure exists but isn't initialised yet.
    yesterday_text, yesterday_unit = (
        format_energy_kwh(yesterday_kwh, "") if yesterday_kwh is not None else ("—", "kWh"))
    avg_text, avg_unit = format_energy_kwh(avg, "/j") if past else ("—", "kWh/j")
    return {
        "yesterday_text": yesterday_text,
        "yesterday_unit": yesterday_unit,
        "yesterday_kwh": yesterday_kwh,  # numeric, for the peak-hours alert
        "yesterday_hc_kwh": yesterday_hc_kwh,
        "avg_text": avg_text,
        "avg_unit": avg_unit,
        "avg_kwh": avg if past else None,  # numeric (kWh) for sorting + alert money
        "trend_pct": trend_pct,
        "hc_pct": _hc_pct(slugs, nine_ago, today_str),  # int 0..100 or None (no HC info yet)
        # Prior-period HC share (same window as the trend) for the alert that
        # spots a plug drifting out of the off-peak hours.
        "hc_pct_prev": _hc_pct(slugs, prev_start, nine_ago),
        "spark": _group_spark(slugs, today, today_str),
    }


def attach(data: dict):
    """Attach one bottom-table entry per group (label) — topics sharing a label
    are summed (yesterday kWh + recent average).

    Integrated from each device's reported power (no energy counter); history
    starts at first connection (no backfill).
    """
    from app.electricity import power

    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    data["power_sensors"] = [
        {"name": name, **_group_stats(slugs, today, today_str)}
        for name, slugs in power._groups(power.SENSORS)
    ]


def status() -> dict:
    from app.electricity import power
    from app.electricity.power import command

    return {"power_enabled": power.ENABLED, "last_power": dict(command._last_report)}
