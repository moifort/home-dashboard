"""Electricity domain business rules — pure derivations from the daily HC/HP days.

No IO: builds the consumption panel (recent days), the HC/HP + price stats and the
talon (baseline-power) panel from a list of cached days.
"""
from datetime import datetime

from app.system.config import DAYS_FR


def build_core(days: list[dict], now: datetime, price_hp: float, price_hc: float,
               price_abo_monthly: float) -> dict:
    """Build the base render dict (the consumption days + stats + talon)."""
    today = now.strftime("%Y-%m-%d")
    complete_days = [d for d in days if d["date"] < today]

    current_week = complete_days[-9:]
    prev_weeks = complete_days[-37:-9]

    result = []
    for d in current_week:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        result.append({
            "day": DAYS_FR[dt.weekday()],
            "date": d["date"],
            "hc_kwh": d["hc_kwh"],
            "hp_kwh": d["hp_kwh"],
        })

    return {
        "days": result,
        "stats": _compute_stats(current_week, prev_weeks, price_hp, price_hc, price_abo_monthly),
        "talon": _compute_talon(current_week, prev_weeks),
    }


def _compute_talon(current: list[dict], previous: list[dict]) -> dict:
    """Baseline-power panel: yesterday's talon, the recent daily average and its
    trend. A rising talon means more standby waste, so it reads as bad (red)."""
    def _vals(days):
        return [d["talon_w"] for d in days if d.get("talon_w") is not None]

    cur = _vals(current)
    yesterday = cur[-1] if cur else None
    avg = sum(cur) / len(cur) if cur else 0.0

    prev = _vals(previous)
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100, 1) if avg_prev > 0 else 0

    # Sparkline: the last 7 complete days' talon (oldest→newest, ending
    # yesterday), left-padded with None when fewer than 7 days are available.
    last7 = [d.get("talon_w") for d in current[-7:]]
    spark = [None] * (7 - len(last7)) + last7

    return {
        "yesterday_text": f"{round(yesterday)}" if yesterday is not None else "N/A",
        "avg_text": f"{round(avg)}" if cur else "N/A",
        "avg_w": round(avg) if cur else None,
        "trend_pct": trend_pct,
        "spark": spark,
    }


def _compute_stats(current: list[dict], previous: list[dict], price_hp: float,
                   price_hc: float, price_abo_monthly: float) -> dict:
    daily_abo = price_abo_monthly / 30.44
    na_threshold = 1.0

    def _filter_valid(days):
        return [d for d in days if d["hc_kwh"] + d["hp_kwh"] >= na_threshold]

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

    avg_kwh, hc_ratio, avg_price = _avg_and_ratios(_filter_valid(current))
    has_prev = len(previous) > 0
    avg_kwh_prev, hc_ratio_prev, avg_price_prev = _avg_and_ratios(_filter_valid(previous))

    def _pct(cur, prev):
        if not has_prev or prev == 0:
            return 0
        return round((cur - prev) / prev * 100, 1)

    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": _pct(avg_kwh, avg_kwh_prev),
        "hc_ratio": round(hc_ratio, 1),
        "hc_ratio_pct": round(hc_ratio - hc_ratio_prev, 1) if has_prev else 0,
        "avg_price": round(avg_price, 2),
        "avg_price_pct": _pct(avg_price, avg_price_prev),
    }
