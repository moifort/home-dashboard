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
ELEC_DROP_PCT = 10        # stats.avg_kwh_pct <= -this -> conso en forte baisse
HC_RISE_PTS = 10          # stats.hc_ratio_pct >= -> forte utilisation heures creuses
TALON_DROP_PCT = 25       # talon.trend_pct <= -this -> veille en forte baisse
CUMULUS_DROP_PCT = 25     # cumulus.trend_pct <= -this -> cumulus en forte baisse
PRISE_HC_DROP_PTS = 10    # sensor hc_pct fell by >= this many points vs the prior period


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


# --- Good rules (black) ---

def _elec_drop(data):
    stats = data.get("stats") or {}
    pct = stats.get("avg_kwh_pct")
    if pct is not None and pct <= -ELEC_DROP_PCT:
        avg_price = stats.get("avg_price")
        money = _money(True, avg_price * pct / 100) if avg_price else ""
        return ("Belle baisse de consommation", f"{round(abs(pct))}%/j", money)
    return None


def _hc_high(data):
    stats = data.get("stats") or {}
    pct = stats.get("hc_ratio_pct")
    if pct is not None and pct >= HC_RISE_PTS:
        avg_kwh = stats.get("avg_kwh")
        money = _money(True, avg_kwh * pct / 100 * (PRICE_HP - PRICE_HC)) if avg_kwh else ""
        return ("Belle utilisation des heures creuses", f"{round(pct)}%", money)
    return None


def _talon_drop(data):
    talon = data.get("talon") or {}
    pct = talon.get("trend_pct")
    if pct is not None and pct <= -TALON_DROP_PCT:
        avg_w = talon.get("avg_w")
        money = _money(True, avg_w * abs(pct) / 100 * 24 / 1000 * PRICE_HP) if avg_w else ""
        return ("Consommation de veille en baisse", f"{round(abs(pct))}%", money)
    return None


def _cumulus_drop(data):
    cumulus = _power_sensor(data, "Cumulus") or {}
    pct = cumulus.get("trend_pct")
    if pct is not None and pct <= -CUMULUS_DROP_PCT:
        avg = cumulus.get("avg_kwh")
        money = _money(True, avg * abs(pct) / 100 * PRICE_HC) if avg else ""
        return ("Baisse de consommation du cumulus", f"{round(abs(pct))}%", money)
    return None


RULES = [
    AlertRule("elec_rise", _elec_rise, "EDF", 50, False),
    AlertRule("hc_drop", _hc_drop, "EDF", 35, False),
    AlertRule("talon_rise", _talon_rise, "EDF", 20, False),
    AlertRule("prise_hc_drop", _prise_hc_drop, "Prises", 18, False),
    AlertRule("cumulus_rise", _cumulus_rise, "Prises", 15, False),
    AlertRule("elec_drop", _elec_drop, "EDF", 7, True),
    AlertRule("hc_high", _hc_high, "EDF", 8, True),
    AlertRule("talon_drop", _talon_drop, "EDF", 5, True),
    AlertRule("cumulus_drop", _cumulus_drop, "Prises", 4, True),
]

BOARDS = [
    ("EDF", lambda data: bool(data.get("stats"))),
    ("Prises", lambda data: bool(data.get("power_sensors"))),
]
