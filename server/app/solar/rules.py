"""Solar domain business rules — pure derivations from the production history.

No IO: builds the 9-day production panel and its trend/savings stats from a
{date: pv_kwh} map.
"""
from datetime import datetime, timedelta

from app.system.config import DAYS_FR

def fetch_window(now: datetime) -> tuple[str, str]:
    """The (start, end) date range to read so the 9 shown days and the ~28-day
    trend baseline are covered. End is tomorrow (exclusive) so today's live bar is
    kept."""
    today = now.date()
    full_start = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    return full_start, end


def build_production_panel(prod_by_date: dict, now: datetime, consumption_days: list | None,
                          price_hp: float, pv_profiles: dict | None = None) -> dict:
    """Build the solar production history: always the last 9 days, ending today.

    Days without accumulated data show as N/A. Today is included so its bar grows
    as production accumulates through the day (the EDF chart does the same since
    the ZLinky integrates live).

    `consumption_days` is the core chart's day list (grid import); it feeds the
    autonomy figure. `pv_profiles` maps a date to its 48-slot intraday mean-PV
    profile (None-padded); each shown day carries its profile as `intraday` for
    the mini graph under its bar (None when the date has no sample).
    """
    today = now.date()
    production_days = []
    recent = []
    for i in range(8, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        pv = prod_by_date.get(ds, 0.0)
        production_days.append({"day": DAYS_FR[d.weekday()], "date": ds, "pv_kwh": pv,
                                "today": d == today,
                                "intraday": (pv_profiles or {}).get(ds)})
        recent.append({"pv_kwh": pv})

    previous = [{"pv_kwh": prod_by_date[ds]}
                for i in range(36, 8, -1)
                if (ds := (today - timedelta(days=i)).strftime("%Y-%m-%d")) in prod_by_date]

    stats = _compute_production_stats(recent, previous, price_hp)
    stats["autonomy_pct"] = _compute_autonomy(production_days, consumption_days)
    # Month-to-date savings (self-consumed PV at HP price) + the complete-days
    # figure (up to yesterday) for the home net-cost projection.
    first = today.replace(day=1).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    month = {ds: kwh for ds, kwh in prod_by_date.items() if first <= ds <= today_str}
    stats["month_savings_eur"] = round(sum(month.values()) * price_hp, 2)
    stats["month_savings_complete_eur"] = round(
        sum(kwh for ds, kwh in month.items() if ds < today_str) * price_hp, 2)
    return {"production_days": production_days, "production_stats": stats}


def _compute_autonomy(production_days: list[dict], consumption_days: list | None):
    """Share of the home's consumption the solar covered (%), over the complete
    days both charts have data for.

    The Linky measures grid import, already net of self-consumed solar, so total
    consumption = grid + PV and autonomy = PV / (grid + PV). Model: all PV is
    self-consumed (no export measurement; the micro-inverter is sized well below
    the base load). A day with pv 0.0 is a data gap (real production is never
    exactly zero), so it is skipped rather than counted as a sunless day."""
    cons_by_date = {d["date"]: d["hc_kwh"] + d["hp_kwh"]
                    for d in consumption_days or [] if not d.get("today")}
    pv_sum = grid_sum = 0.0
    for day in production_days:
        grid = cons_by_date.get(day["date"], 0.0)
        if day["today"] or day["pv_kwh"] <= 0 or grid <= 0:
            continue
        pv_sum += day["pv_kwh"]
        grid_sum += grid
    if pv_sum <= 0:
        return None
    return round(pv_sum / (grid_sum + pv_sum) * 100)


def _compute_production_stats(current: list[dict], previous: list[dict], price_hp: float) -> dict:
    def _avg(days):
        # No energy threshold — a null day means "no data", any real production
        # counts toward the average, however small.
        valid = [d for d in days if d["pv_kwh"] > 0]
        if not valid:
            return 0
        return sum(d["pv_kwh"] for d in valid) / len(valid)

    avg_kwh = _avg(current)
    avg_kwh_prev = _avg(previous)
    has_prev = avg_kwh_prev > 0

    pct = round((avg_kwh - avg_kwh_prev) / avg_kwh_prev * 100) if has_prev else 0
    total = sum(d["pv_kwh"] for d in current)
    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": pct,
        "total_kwh": round(total, 1),
        "savings_eur": round(total * price_hp, 1),
    }
