"""Trend-based alert engine for the top-left status board.

Each rule is a pure function (data) -> (message, figure[, money]) | None: a short
*human* sentence, the figure (number + unit) shown at the end, and an optional
money impact (économie/dépense). A *bad* alert renders entirely red, a *good*
highlight (key in GOOD_KEYS) entirely black — red means a problem, black a
positive note. Every rule guards on data.get(...) so a removed integration (its
data key absent) simply never fires. build_board() groups the active items under
their domain (EDF/Eau/Solaire/Réseau/Cumulus/Crypto) and returns the rows the
renderer draws. Thresholds are the named constants below — tune here.
"""

# Electricity price (core Linky) for the €/kWh-based money estimates (standby,
# cumulus, heures-creuses shift, solar). Falls back to defaults if unavailable.
try:
    from app.integrations.linky import PRICE_HC, PRICE_HP
except Exception:  # pragma: no cover - linky is core, this is a safety net
    PRICE_HP, PRICE_HC = 0.2065, 0.1579

# --- Thresholds (tune here) ---
# Bad (red):
ELEC_RISE_PCT = 10        # stats.avg_kwh_pct >= -> conso EDF en hausse
HC_DROP_PTS = 10          # stats.hc_ratio_pct <= -this -> heures creuses en baisse
WATER_LEAK_FACTOR = 2.0   # a finished day > factor x average ...
WATER_LEAK_FLOOR_L = 150  # ... and the excess over this many litres -> leak
SOLAR_DROP_PCT = 30       # production_stats.avg_kwh_pct <= -this -> chute
NET_USAGE_RISE_PCT = 30   # unifi.usage_trend >= -> forte conso Internet
ISP_PCT_MIN = 95          # unifi.isp_pct < -> Internet dégradé
LATENCY_MS_MAX = 50       # unifi.latency_val > -> latence élevée
WIFI_PCT_MIN = 90         # unifi.wifi_pct < -> WiFi dégradé
TALON_RISE_PCT = 25       # talon.trend_pct >= -> veille en hausse
CUMULUS_RISE_PCT = 25     # cumulus.trend_pct >= -> cumulus en hausse
# Good (black):
ELEC_DROP_PCT = 10        # stats.avg_kwh_pct <= -this -> conso en forte baisse
HC_RISE_PTS = 10          # stats.hc_ratio_pct >= -> forte utilisation heures creuses
SOLAR_RISE_PCT = 30       # production_stats.avg_kwh_pct >= -> forte hausse solaire
WATER_DROP_PCT = 20       # water_stats.avg_pct <= -this -> forte baisse eau
TALON_DROP_PCT = 25       # talon.trend_pct <= -this -> veille en forte baisse
CUMULUS_DROP_PCT = 25     # cumulus.trend_pct <= -this -> cumulus en forte baisse

# Per-rule enable flags. Bad alerts + good highlights; all on, trivial to cut.
ENABLED = {
    "elec_rise": True, "hc_drop": True, "water_leak": True,
    "solar_off": True, "solar_drop": True, "net_usage": True,
    "isp_bad": True, "latency": True, "wifi_bad": True,
    "talon_rise": True, "cumulus_rise": True, "crypto_alpha_neg": True,
    "elec_drop": True, "hc_high": True, "solar_high": True,
    "water_drop": True, "talon_drop": True, "cumulus_drop": True,
    "crypto_alpha_pos": True,
}

# Keys that are *positive* highlights (rendered black, not red).
GOOD_KEYS = {"elec_drop", "hc_high", "solar_high", "water_drop", "talon_drop",
             "cumulus_drop", "crypto_alpha_pos"}

# Severity: higher = more urgent, shown first. Outages/health, then bad trends,
# then (lowest) the good highlights so problems always sit above positives.
SEVERITY = {
    "isp_bad": 100, "solar_off": 95, "water_leak": 90, "wifi_bad": 80, "latency": 70,
    "elec_rise": 50, "net_usage": 45, "solar_drop": 40, "hc_drop": 35,
    "crypto_alpha_neg": 30, "talon_rise": 20, "cumulus_rise": 15,
    "solar_high": 9, "hc_high": 8, "elec_drop": 7, "water_drop": 6,
    "talon_drop": 5, "cumulus_drop": 4, "crypto_alpha_pos": 3,
}


def _to_float(text):
    """Parse a display string ('153', '18,0', 'N/A', None) to float, or None."""
    if isinstance(text, (int, float)):
        return float(text)
    if text is None:
        return None
    s = str(text).strip().replace(",", ".")
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _eur(value):
    """Euro amount with a French decimal comma, e.g. 0.39 -> '0,39'."""
    return f"{abs(value):.2f}".replace(".", ",")


def _money(good, amount, unit="€/j"):
    """A money phrase: 'économie X€/j' (good) or 'dépense X€/j' (bad). The currency
    symbol is glued to the amount so it never wraps onto a line of its own."""
    return f"{'économie' if good else 'dépense'} {_eur(amount)}{unit}"


def _usd(text):
    """Parse a '$11 234' / '+$1 234' / '-$1 234' display amount to float, or None."""
    if not text:
        return None
    s = str(text).replace("$", "").replace("+", "").replace(" ", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _usd_fmt(value):
    """Whole-dollar amount with a plain-space thousands separator (Arial-safe)."""
    return f"{round(abs(value)):,}".replace(",", " ")


def _power_sensor(data, name):
    """Find a configured power sensor by its display name (case-insensitive)."""
    for s in data.get("power_sensors") or []:
        if s.get("name", "").lower() == name.lower():
            return s
    return None


def _crypto_alpha_gain(crypto, alpha):
    """$ the strategy earned over buy-and-hold = invested x alpha%.
    invested = portfolio - profit. Returns None if the amounts can't be parsed."""
    portfolio = _usd(crypto.get("portfolio_text"))
    profit = _usd(crypto.get("profit_text"))
    if portfolio is None or profit is None:
        return None
    return (portfolio - profit) * alpha / 100


# --- Bad rules (red): each returns (human message, figure[, money]) or None ---

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


def _net_usage(data):
    pct = (data.get("unifi") or {}).get("usage_trend")
    if pct is not None and pct >= NET_USAGE_RISE_PCT:
        return ("Forte consommation Internet", f"{round(pct)}%/j")
    return None


def _isp_bad(data):
    unifi = data.get("unifi") or {}
    if not unifi:
        return None
    pct = unifi.get("isp_pct")
    has_pct = isinstance(pct, (int, float))
    if unifi.get("isp_bad") or (has_pct and pct < ISP_PCT_MIN):
        return ("Connexion Internet dégradée", f"{round(pct)}%" if has_pct else "")
    return None


def _latency(data):
    ms = _to_float((data.get("unifi") or {}).get("latency_val"))
    if ms is not None and ms > LATENCY_MS_MAX:
        return ("Latence réseau élevée", f"{round(ms)} ms")
    return None


def _wifi_bad(data):
    unifi = data.get("unifi") or {}
    if not unifi:
        return None
    pct = unifi.get("wifi_pct")
    has_pct = isinstance(pct, (int, float))
    if unifi.get("wifi_bad") or (has_pct and pct < WIFI_PCT_MIN):
        return ("Wi-Fi dégradé", f"{round(pct)}%" if has_pct else "")
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
        avg = _to_float(cumulus.get("avg_text"))
        money = _money(False, avg * pct / 100 * PRICE_HC) if avg else ""
        return ("Forte consommation du cumulus", f"{round(pct)}%", money)
    return None


def _crypto_alpha_neg(data):
    c = data.get("crypto") or {}
    alpha = _to_float(c.get("alpha_text"))
    if alpha is None or alpha >= 0:
        return None
    gain = _crypto_alpha_gain(c, alpha)
    money = f"manque {_usd_fmt(gain)}$" if gain else ""
    return ("Bot derrière le hold", f"{round(alpha)}%", money)


# --- Good rules (black): strong positive trends worth surfacing ---

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


def _solar_high(data):
    stats = data.get("production_stats") or {}
    pct = stats.get("avg_kwh_pct")
    if pct is not None and pct >= SOLAR_RISE_PCT:
        sav = stats.get("savings_eur")
        money = f"économie {_eur(sav)}€" if sav else ""
        return ("Forte production solaire", f"{round(pct)}%", money)
    return None


def _water_drop(data):
    stats = data.get("water_stats") or {}
    pct = stats.get("avg_pct")
    if pct is not None and pct <= -WATER_DROP_PCT:
        avg = _to_float(stats.get("avg_text"))
        cost = _to_float(stats.get("cost_text"))
        m3 = _to_float(stats.get("month_total_text"))
        money = (f"économie {_eur(avg * abs(pct) / 100 / 1000 * (cost / m3))}€/j"
                 if (avg and cost and m3 and m3 > 0) else "")
        return ("Belle baisse de consommation d'eau", f"{round(abs(pct))}%", money)
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
        avg = _to_float(cumulus.get("avg_text"))
        money = _money(True, avg * abs(pct) / 100 * PRICE_HC) if avg else ""
        return ("Baisse de consommation du cumulus", f"{round(abs(pct))}%", money)
    return None


def _crypto_alpha_pos(data):
    c = data.get("crypto") or {}
    alpha = _to_float(c.get("alpha_text"))
    if alpha is None or alpha <= 0:
        return None
    gain = _crypto_alpha_gain(c, alpha)
    money = f"gain {_usd_fmt(gain)}$" if gain else ""
    return ("Bot devant le hold", f"+{round(alpha)}%", money)


_RULES = [
    # Bad (red)
    ("elec_rise", _elec_rise), ("hc_drop", _hc_drop), ("water_leak", _water_leak),
    ("solar_off", _solar_off), ("solar_drop", _solar_drop), ("net_usage", _net_usage),
    ("isp_bad", _isp_bad), ("latency", _latency), ("wifi_bad", _wifi_bad),
    ("talon_rise", _talon_rise), ("cumulus_rise", _cumulus_rise), ("crypto_alpha_neg", _crypto_alpha_neg),
    # Good (black)
    ("elec_drop", _elec_drop), ("hc_high", _hc_high), ("solar_high", _solar_high),
    ("water_drop", _water_drop), ("talon_drop", _talon_drop), ("cumulus_drop", _cumulus_drop),
    ("crypto_alpha_pos", _crypto_alpha_pos),
]


def build_alerts(data: dict) -> list[dict]:
    """Run every enabled rule; return the raw active items (grouping happens in
    build_board). Each item is {"key", "message", "figure", "money", "severity",
    "good"}; a rule may omit the trailing money string. A rule that raises is
    treated as 'no alert' — a render must never crash on a malformed value.
    """
    alerts = []
    for key, rule in _RULES:
        if not ENABLED.get(key, False):
            continue
        try:
            res = rule(data)
        except Exception:
            res = None
        if res:
            message, figure = res[0], res[1]
            money = res[2] if len(res) > 2 else ""
            alerts.append({"key": key, "message": message, "figure": figure, "money": money,
                           "severity": SEVERITY.get(key, 0), "good": key in GOOD_KEYS})
    return alerts


# --- Always-on status board: one row per monitored domain ---

# Each rule belongs to a domain. The board shows one row per *monitored* domain
# (its source data present): a domain with active items lists them under its
# section title (problems first, then positives), a quiet domain shows "Rien à
# signaler". DOMAINS order is the canonical order of the quiet rows.
DOMAINS = ["EDF", "Eau", "Solaire", "Réseau", "Cumulus", "Crypto"]

RULE_DOMAIN = {
    "elec_rise": "EDF", "hc_drop": "EDF", "talon_rise": "EDF",
    "elec_drop": "EDF", "hc_high": "EDF", "talon_drop": "EDF",
    "water_leak": "Eau", "water_drop": "Eau",
    "solar_off": "Solaire", "solar_drop": "Solaire", "solar_high": "Solaire",
    "net_usage": "Réseau", "isp_bad": "Réseau", "latency": "Réseau", "wifi_bad": "Réseau",
    "cumulus_rise": "Cumulus", "cumulus_drop": "Cumulus",
    "crypto_alpha_pos": "Crypto", "crypto_alpha_neg": "Crypto",
}


def _domain_present(data: dict, domain: str) -> bool:
    """True when the domain's source data is attached (so it can be evaluated)."""
    return {
        "EDF": bool(data.get("stats")),
        "Eau": bool(data.get("water_stats") or data.get("water_days")),
        "Solaire": bool(data.get("production_stats") or data.get("production_days")),
        "Réseau": bool(data.get("unifi")),
        "Cumulus": bool(_power_sensor(data, "Cumulus")),
        "Crypto": bool(data.get("crypto")),
    }.get(domain, False)


def build_board(data: dict) -> list[dict]:
    """Build the always-on status board rows the renderer draws.

    One row per *monitored* domain (its data present). A domain with active items
    carries them, most severe first (problems above positives):
        {"label": dom, "alert": True, "severity": int,
         "items": [(message, figure, money, good), ...]}
    A quiet domain is {"label": dom, "alert": False, "severity": -1}. Domains with
    items come first (most severe on top), then the quiet rows in canonical order.
    """
    by_domain = {}
    for a in build_alerts(data):
        dom = RULE_DOMAIN.get(a["key"])
        if dom:
            by_domain.setdefault(dom, []).append(a)

    rows = []
    for dom in DOMAINS:
        if not _domain_present(data, dom):
            continue
        items = by_domain.get(dom)
        if items:
            items.sort(key=lambda a: a["severity"], reverse=True)
            n_bad = sum(1 for a in items if not a["good"])
            rows.append({
                "label": dom, "alert": True, "severity": items[0]["severity"], "n_bad": n_bad,
                "items": [(a["message"], a["figure"], a["money"], a["good"]) for a in items],
            })
        else:
            rows.append({"label": dom, "alert": False, "severity": -1, "n_bad": 0})

    # Vertical space is limited, so list the domains with the most problems first
    # (then by severity); domains with only positive notes next; quiet rows last.
    rows.sort(key=lambda r: (not r["alert"], -r["n_bad"], -r["severity"]))
    return rows
