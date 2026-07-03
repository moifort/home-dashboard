"""Electricity domain alerts — the EDF and Prises status-board sections.

Each rule is a pure function (data) -> (message, figure[, money]) | None. EDF
covers consumption, heures-creuses and the talon (baseline power); Prises covers
the power sensors (the water-heater Cumulus looked up by display name in
data["power_sensors"], plus the per-plug off-peak drift rule).
"""
from app.module.format import AlertRule, _money

# Electricity prices for the €/kWh-based money estimates.
from app.electricity import PRICE_HC, PRICE_HP

# --- Thresholds (tune here) ---
ELEC_RISE_PCT = 10        # stats.avg_kwh_pct >= -> conso EDF en hausse
HC_DROP_PTS = 10          # stats.hc_ratio_pct <= -this -> heures creuses en baisse
TALON_RISE_PCT = 25       # talon.trend_pct >= -> veille en hausse
CUMULUS_RISE_PCT = 25     # cumulus.trend_pct >= -> cumulus en hausse
PRISE_HC_DROP_PTS = 10    # sensor hc_pct fell by >= this many points vs the prior period
CUMULUS_HP_SHARE_PCT = 30  # % of yesterday's cumulus energy on peak hours -> alert
CUMULUS_HP_MIN_KWH = 1.0   # ignore below this much energy (a quiet day)


def _power_sensor(data, name):
    """Find a configured power sensor by its display name (case-insensitive)."""
    for s in data.get("power_sensors") or []:
        if s.get("name", "").lower() == name.lower():
            return s
    return None


# --- Bad rules (red) ---

def _elec_rise(data):
    stats = data.get("stats") or {}
    pct = stats.get("avg_kwh_pct")
    if pct is not None and pct >= ELEC_RISE_PCT:
        avg_price = stats.get("avg_price")
        money = _money(False, avg_price * pct / 100) if avg_price else ""
        return ("Forte hausse de consommation", f"{round(pct)}%/j", money)
    return None


def _hc_drop(data):
    stats = data.get("stats") or {}
    pct = stats.get("hc_ratio_pct")
    if pct is not None and pct <= -HC_DROP_PTS:
        avg_kwh = stats.get("avg_kwh")
        money = _money(False, avg_kwh * abs(pct) / 100 * (PRICE_HP - PRICE_HC)) if avg_kwh else ""
        return ("Heures creuses en forte baisse", f"{round(abs(pct))}%", money)
    return None


def _talon_rise(data):
    talon = data.get("talon") or {}
    pct = talon.get("trend_pct")
    if pct is not None and pct >= TALON_RISE_PCT:
        avg_w = talon.get("avg_w")
        money = _money(False, avg_w * pct / 100 * 24 / 1000 * PRICE_HP) if avg_w else ""
        return ("Consommation de veille en hausse", f"{round(pct)}%", money)
    return None


def _cumulus_rise(data):
    cumulus = _power_sensor(data, "Cumulus") or {}
    pct = cumulus.get("trend_pct")
    if pct is not None and pct >= CUMULUS_RISE_PCT:
        avg = cumulus.get("avg_kwh")
        money = _money(False, avg * pct / 100 * PRICE_HC) if avg else ""
        return ("Forte consommation du cumulus", f"{round(pct)}%", money)
    return None


def _prise_hc_drop(data):
    """A plug drifting out of the off-peak hours: its recent HC share fell by
    PRISE_HC_DROP_PTS points or more vs the prior period. Reports the worst
    offender (one board line); the shifted kWh are billed at the HP premium."""
    worst = None
    for s in data.get("power_sensors") or []:
        cur, prev = s.get("hc_pct"), s.get("hc_pct_prev")
        if cur is None or prev is None:
            continue
        drop = prev - cur
        if drop >= PRISE_HC_DROP_PTS and (worst is None or drop > worst[1]):
            worst = (s, drop)
    if worst:
        s, drop = worst
        avg = s.get("avg_kwh")
        money = _money(False, avg * drop / 100 * (PRICE_HP - PRICE_HC)) if avg else ""
        return (f"Heures creuses {s.get('name', '')} en baisse", f"{round(drop)}pts", money)
    return None


def _cumulus_hp(data):
    """The water heater ran on peak hours yesterday (stuck contactor, drifted
    clock): its HP share of the day crossed the threshold. The shifted kWh are
    billed at the HC→HP premium. Needs the off-peak split (hc None = pre-feature
    day, stays quiet)."""
    cumulus = _power_sensor(data, "Cumulus") or {}
    total, hc = cumulus.get("yesterday_kwh"), cumulus.get("yesterday_hc_kwh")
    if total is None or hc is None or total < CUMULUS_HP_MIN_KWH:
        return None
    hp_kwh = max(0.0, total - hc)
    share = hp_kwh / total * 100
    if share >= CUMULUS_HP_SHARE_PCT:
        return ("Cumulus chauffé en heures pleines", f"{round(share)}%",
                _money(False, hp_kwh * (PRICE_HP - PRICE_HC), unit="€"))
    return None


# No "good" rules here: positive trends already show on the EDF banner and the
# bottom table (▼ arrows) — the board is reserved for anomalies to act on.

RULES = [
    AlertRule("elec_rise", _elec_rise, "EDF", 50, False),
    AlertRule("hc_drop", _hc_drop, "EDF", 35, False),
    AlertRule("cumulus_hp", _cumulus_hp, "Prises", 22, False),
    AlertRule("talon_rise", _talon_rise, "EDF", 20, False),
    AlertRule("prise_hc_drop", _prise_hc_drop, "Prises", 18, False),
    AlertRule("cumulus_rise", _cumulus_rise, "Prises", 15, False),
]

BOARDS = [
    ("EDF", lambda data: bool(data.get("stats"))),
    ("Prises", lambda data: bool(data.get("power_sensors"))),
]
