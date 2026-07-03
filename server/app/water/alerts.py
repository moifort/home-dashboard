"""Water domain alerts — the "Eau" status-board section (leak)."""
from app.module.format import AlertRule, _eur, _to_float

WATER_LEAK_FACTOR = 2.0   # a finished day > factor x average ...
WATER_LEAK_FLOOR_L = 150  # ... and the excess over this many litres -> leak


def _water_leak(data):
    stats = data.get("water_stats") or {}
    avg = _to_float(stats.get("avg_text"))
    if avg is None or avg <= 0:
        return None
    finished = [d for d in (data.get("water_days") or [])
                if not d.get("today") and d.get("liters")]
    if not finished:
        return None
    last = finished[-1]["liters"]
    if last > WATER_LEAK_FACTOR * avg and (last - avg) > WATER_LEAK_FLOOR_L:
        excess = last - avg
        # Cost of the excess litres, if a €/m³ can be derived (cost ÷ m³ MTD).
        cost = _to_float(stats.get("cost_text"))
        m3 = _to_float(stats.get("month_total_text"))
        money = f"dépense {_eur(excess / 1000 * (cost / m3))}€" if (cost and m3 and m3 > 0) else ""
        return ("Fuite d'eau probable", f"{round(excess)} L", money)
    return None


# No "good" rule: a falling average already shows on the Eau banner's ▼ trend —
# the board is reserved for anomalies to act on.

RULES = [
    AlertRule("water_leak", _water_leak, "Eau", 90, False),
]

BOARDS = [
    ("Eau", lambda data: bool(data.get("water_stats") or data.get("water_days"))),
]
