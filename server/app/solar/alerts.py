"""Solar domain alerts — the "Solaire" status-board section."""
from app.module.format import AlertRule, _money

from app.solar import PRICE_HP

SOLAR_DROP_PCT = 30       # production_stats.avg_kwh_pct <= -this -> chute


def _solar_off(data):
    finished = [d for d in (data.get("production_days") or []) if not d.get("today")]
    if finished and finished[-1].get("pv_kwh", 0) == 0:
        return ("Panneaux solaires déconnectés ?", "0 kWh")
    return None


def _solar_drop(data):
    # Suppressed when solar_off already fired (avoid a duplicate).
    if _solar_off(data) is not None:
        return None
    stats = data.get("production_stats") or {}
    pct = stats.get("avg_kwh_pct")
    if pct is not None and pct <= -SOLAR_DROP_PCT:
        avg = stats.get("avg_kwh")
        money = _money(False, avg * abs(pct) / 100 * PRICE_HP) if avg else ""
        return ("Production solaire en baisse", f"{round(abs(pct))}%", money)
    return None


def _solar_record(data):
    """Yesterday broke the all-time daily production record — an event, not a
    restatement of the banner (which the removed 'forte production' note was).
    The record_kwh field is set by attach() once enough history exists."""
    kwh = (data.get("production_stats") or {}).get("record_kwh")
    if kwh:
        return ("Record de production solaire", f"{kwh:.2f}kWh")
    return None


RULES = [
    AlertRule("solar_off", _solar_off, "Solaire", 95, False),
    AlertRule("solar_drop", _solar_drop, "Solaire", 40, False),
    AlertRule("solar_record", _solar_record, "Solaire", 9, True),
]

BOARDS = [
    ("Solaire", lambda data: bool(data.get("production_stats") or data.get("production_days"))),
]
