"""Network domain alerts — the "Réseau" status-board section."""
from app.module.format import AlertRule, _to_float

NET_USAGE_RISE_PCT = 30   # unifi.usage_trend >= -> forte conso Internet
ISP_PCT_MIN = 95          # unifi.isp_pct < -> Internet dégradé
LATENCY_MS_MAX = 50       # unifi.latency_val > -> latence élevée
WIFI_PCT_MIN = 90         # unifi.wifi_pct < -> WiFi dégradé


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


RULES = [
    AlertRule("isp_bad", _isp_bad, "Réseau", 100, False),
    AlertRule("wifi_bad", _wifi_bad, "Réseau", 80, False),
    AlertRule("latency", _latency, "Réseau", 70, False),
    AlertRule("net_usage", _net_usage, "Réseau", 45, False),
]

BOARDS = [
    ("Réseau", lambda data: bool(data.get("unifi"))),
]
