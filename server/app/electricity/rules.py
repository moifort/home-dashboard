"""Electricity domain business rules — pure derivations from the daily HC/HP days.

No IO: builds the consumption panel (recent days), the HC/HP + price stats and the
talon (baseline-power) panel from a list of cached days.
"""
from datetime import datetime, timedelta

from app.module.format import format_cost_eur
from app.system.config import DAYS_FR


def build_core(days: list[dict], now: datetime, price_hp: float, price_hc: float,
               price_abo_monthly: float, papp_profiles: dict | None = None) -> dict:
    """Build the base render dict (the consumption days + stats + talon).

    `papp_profiles` maps a date to its 48-slot intraday mean-PAPP profile
    (None-padded); each shown day carries its profile as `intraday` for the
    mini graph under its EDF bar (None when the date has no TIC sample yet).
    """
    today = now.strftime("%Y-%m-%d")
    complete_days = [d for d in days if d["date"] < today]

    # Stats stay on complete days only — a partial day would drag every average
    # down. The chart swaps the oldest column for today's live "Auj." bar instead
    # (the ZLinky integrates since midnight, so today's row grows through the day).
    current_week = complete_days[-9:]
    prev_weeks = complete_days[-37:-9]

    # The chart window is anchored on the calendar (the 8 days before today +
    # today), not on the rows present in DB: a missing day (server down, data
    # purged) must show as an N/A column, not silently shift the window.
    by_date = {d["date"]: d for d in days}
    shown_dates = [(now - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(8, -1, -1)]
    shown = [by_date.get(date, {"date": date, "hc_kwh": 0.0, "hp_kwh": 0.0}) for date in shown_dates]

    result = []
    for d in shown:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        result.append({
            "day": DAYS_FR[dt.weekday()],
            "date": d["date"],
            "hc_kwh": d["hc_kwh"],
            "hp_kwh": d["hp_kwh"],
            "today": d["date"] == today,
            "intraday": (papp_profiles or {}).get(d["date"]),
        })

    stats = _compute_stats(current_week, prev_weeks, price_hp, price_hc, price_abo_monthly)
    stats.update(_month_cost(days, now, price_hp, price_hc, price_abo_monthly))
    return {
        "days": result,
        "stats": stats,
        "talon": _compute_talon(current_week, prev_weeks, price_hp, price_hc),
    }


def _month_cost(days: list[dict], now: datetime, price_hp: float, price_hc: float,
                price_abo_monthly: float) -> dict:
    """Month-to-date electricity cost (consumption at HC/HP prices + the
    subscription prorated per elapsed day), plus the same figure on complete
    days only (up to yesterday) — the clean base for an end-of-month projection
    (today's partial row would drag it down). Also exposes the subscription's
    own month-to-date share so the render can break it out of the total."""
    first = now.strftime("%Y-%m-01")
    today = now.strftime("%Y-%m-%d")
    daily_abo = price_abo_monthly / 30.44

    def _cost(rows):
        return sum(r["hc_kwh"] * price_hc + r["hp_kwh"] * price_hp for r in rows)

    month_rows = [d for d in days if first <= d["date"] <= today]
    complete_rows = [d for d in month_rows if d["date"] < today]
    return {
        "month_cost_eur": round(_cost(month_rows) + daily_abo * now.day, 2),
        "month_cost_complete_eur": round(_cost(complete_rows) + daily_abo * (now.day - 1), 2),
        "month_abo_eur": round(daily_abo * now.day, 2),
    }


# The talon runs 24/7; without the learned tariff windows at hand, price its
# year at the typical HC share of a day (2×4h off-peak windows).
TALON_HC_HOURS = 8


def _compute_talon(current: list[dict], previous: list[dict],
                   price_hp: float, price_hc: float) -> dict:
    """Baseline-power panel: yesterday's talon, the recent daily average and its
    trend. A rising talon means more standby waste, so it reads as bad (red).
    Also prices the average talon over a year ('460€/an') — the figure that
    makes standby waste concrete."""
    def _vals(days):
        return [d["talon_w"] for d in days if d.get("talon_w") is not None]

    cur = _vals(current)
    yesterday = cur[-1] if cur else None
    avg = sum(cur) / len(cur) if cur else 0.0

    prev = _vals(previous)
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100) if avg_prev > 0 else 0

    # Sparkline: the last 7 complete days' talon (oldest→newest, ending
    # yesterday), left-padded with None when fewer than 7 days are available.
    last7 = [d.get("talon_w") for d in current[-7:]]
    spark = [None] * (7 - len(last7)) + last7

    # Annual cost of the average talon: kW × (HC hours at HC price + the rest
    # at HP price) × 365 — an estimate, so it displays whole euros.
    annual_eur = (avg / 1000) * (TALON_HC_HOURS * price_hc
                                 + (24 - TALON_HC_HOURS) * price_hp) * 365 if cur else None

    # "—" = the figure exists but isn't initialised yet (no talon recorded).
    return {
        "yesterday_text": f"{round(yesterday)}" if yesterday is not None else "—",
        "avg_text": f"{round(avg)}" if cur else "—",
        "avg_w": round(avg) if cur else None,
        "annual_text": f"{round(annual_eur)}" if annual_eur is not None else None,
        # Same estimate spread over a month, for the bottom table's cost column.
        "cost_text": format_cost_eur(annual_eur / 12) if annual_eur is not None else "—",
        "trend_pct": trend_pct,
        "spark": spark,
    }


def _compute_stats(current: list[dict], previous: list[dict], price_hp: float,
                   price_hc: float, price_abo_monthly: float) -> dict:
    daily_abo = price_abo_monthly / 30.44

    def _filter_valid(days):
        # No energy threshold — only a day with no data at all (null total) is
        # excluded; every real value counts, however small.
        return [d for d in days if d["hc_kwh"] + d["hp_kwh"] > 0]

    def _avg_and_ratios(days):
        if not days:
            return 0, 0, 0
        total_hc = sum(d["hc_kwh"] for d in days)
        total_hp = sum(d["hp_kwh"] for d in days)
        total = total_hc + total_hp
        n = len(days)
        avg_kwh = total / n
        hc_ratio = (total_hc / total * 100) if total > 0 else 0
        avg_price = ((total_hp * price_hp + total_hc * price_hc) / n) + daily_abo
        return avg_kwh, hc_ratio, avg_price

    valid_cur = _filter_valid(current)
    avg_kwh, hc_ratio, avg_price = _avg_and_ratios(valid_cur)
    has_prev = len(previous) > 0
    avg_kwh_prev, hc_ratio_prev, avg_price_prev = _avg_and_ratios(_filter_valid(previous))

    def _pct(cur, prev):
        if not valid_cur or not has_prev or prev == 0:
            return 0
        return round((cur - prev) / prev * 100)

    # With no valid day yet the values are None — the renderer shows an em dash
    # with the unit kept (a figure that exists but isn't initialised).
    return {
        "avg_kwh": round(avg_kwh, 1) if valid_cur else None,
        "avg_kwh_pct": _pct(avg_kwh, avg_kwh_prev),
        "hc_ratio": round(hc_ratio, 1) if valid_cur else None,
        "hc_ratio_pct": round(hc_ratio - hc_ratio_prev) if (valid_cur and has_prev) else 0,
        "avg_price": round(avg_price, 2) if valid_cur else None,
        "avg_price_pct": _pct(avg_price, avg_price_prev),
    }
