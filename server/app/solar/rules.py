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


def build_production_panel(prod_by_date: dict, now: datetime, talon: dict | None,
                          price_hp: float) -> dict:
    """Build the solar production history: always the last 9 days, ending today.

    Days without accumulated data show as N/A. Today is included so its bar grows
    as production accumulates through the day (the EDF chart can't do this — it
    has no same-day data).
    """
    today = now.date()
    production_days = []
    recent = []
    for i in range(8, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        pv = prod_by_date.get(ds, 0.0)
        production_days.append({"day": DAYS_FR[d.weekday()], "date": ds, "pv_kwh": pv,
                                "today": d == today})
        recent.append({"pv_kwh": pv})

    previous = [{"pv_kwh": prod_by_date[ds]}
                for i in range(36, 8, -1)
                if (ds := (today - timedelta(days=i)).strftime("%Y-%m-%d")) in prod_by_date]

    stats = _compute_production_stats(recent, previous, price_hp)
    # Share of the base load (talon) the solar covers: average daily PV energy
    # over the talon's average daily energy (W → kWh/day). Core Linky runs before
    # the optional slices, so the talon is already populated.
    talon_w = (talon or {}).get("avg_w")
    if talon_w and talon_w > 0:
        talon_kwh = talon_w * 24 / 1000
        stats["talon_cover_pct"] = round(stats["avg_kwh"] / talon_kwh * 100)
    return {"production_days": production_days, "production_stats": stats}


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

    pct = round((avg_kwh - avg_kwh_prev) / avg_kwh_prev * 100, 1) if has_prev else 0
    total = sum(d["pv_kwh"] for d in current)
    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": pct,
        "total_kwh": round(total, 1),
        "savings_eur": round(total * price_hp, 1),
    }
