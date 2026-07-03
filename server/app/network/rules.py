"""Network domain business rules — pure derivations from the gateway payloads.

No IO: turns the raw UniFi dashboard/clients/daily-report data into the
render-ready "Réseau" panel, and computes the data-usage windows + trends.
"""
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ

HEALTH_BAD_PCT = 99  # internet/Wi-Fi quality below this reads as degraded (red)
TREND_DAYS = 7  # the latest completed day is compared to this many prior days
ROLLING_DAYS = 30  # data-usage window: this many complete days ending yesterday

# Snapshot columns that carry a 7-day ▲▼ trend, paired with the panel key they
# fill. (Data usage is NOT here: its trend compares the last 30 days to the prior
# 30, computed directly from the daily report — see build_unifi_panel.)
_TREND_COLUMNS = (
    ("latency_ms", "latency_trend"),
    ("isp_pct", "isp_trend"),
    ("wifi_pct", "wifi_trend"),
)


def _dig(obj, *path, default=None):
    """Safe nested lookup across dicts (str keys) and lists (int indices)."""
    cur = obj
    for p in path:
        if isinstance(p, int):
            if isinstance(cur, list) and -len(cur) <= p < len(cur):
                cur = cur[p]
            else:
                return default
        elif isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return default if cur is None else cur


def _gb(num_bytes: float) -> str:
    """Bytes -> 'X,Y' gigabytes (French decimal comma; the unit is drawn apart)."""
    return f"{(num_bytes or 0) / 1e9:.1f}".replace(".", ",")


def _short(name: str, limit: int = 35) -> str:
    name = (name or "?").strip()
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _client_bytes(c: dict) -> int:
    """Session traffic for a client (rx+tx); active-clients has no usage_bytes."""
    return int((c.get("rx_bytes", 0) or 0) + (c.get("tx_bytes", 0) or 0))


def _network(clients: list, ssid: str, label: str) -> dict:
    """Client count + top-5 by total traffic for one SSID (wireless only)."""
    members = [c for c in clients if not c.get("is_wired") and c.get("essid") == ssid]
    members.sort(key=_client_bytes, reverse=True)
    top = [
        (_short(c.get("display_name") or c.get("hostname") or c.get("mac", "?")),
         _gb(_client_bytes(c)))
        for c in members[:5]
    ]
    return {"label": label, "count": len(members), "top": top}


def build_unifi_panel(raw: dict, ssids: dict) -> dict | None:
    """Derive the render-ready panel fields from the raw gateway data.

    Numbers and their units are kept apart (the renderer draws units in regular
    weight, glued to the bold number). Returns None when the dashboard payload is
    missing. Carries a "_snap" block consumed by attach() for the trend history.
    """
    dash = raw.get("dashboard")
    clients = raw.get("clients") or []
    if not isinstance(dash, dict) or not isinstance(clients, list):
        return None

    # --- Internet (ISP): provider name + health from the routability widget and
    # the per-sample health history (each sample flags WAN downtime over the
    # dashboard's ~24h window).
    isp_name = (_dig(dash, "wan_routability_info", 0, "isp_name", default="") or "").split(" ")[0]
    history = _dig(dash, "internet", "health_history", default=[]) or []
    link_up = not (history[-1].get("wan_downtime") if history else False)
    if history:
        good = sum(1 for h in history if not h.get("wan_downtime"))
        isp_pct = round(good / len(history) * 100)
    else:
        isp_pct = 100 if link_up else 0
    isp_bad = (not link_up) or isp_pct < HEALTH_BAD_PCT

    # --- Internet latency: average WAN latency over the dashboard window.
    wan_hist = _dig(dash, "wan_activity", "activity_by_network_group", "WAN", "history",
                    default=[]) or []
    lats = [h.get("avg_latency_ms") for h in wan_hist if h.get("avg_latency_ms") is not None]
    latency_ms = round(sum(lats) / len(lats)) if lats else 0

    # --- Wi-Fi quality: per-standard satisfaction averaged, weighted by the
    # number of stations (a lightly-used standard shouldn't drag the figure down).
    wt = [s for s in (_dig(dash, "wifi_technology", "summary", default=[]) or [])
          if s.get("satisfaction") is not None]
    sta_total = sum(s.get("num_sta", 0) or 0 for s in wt)
    if sta_total:
        wifi_pct = round(sum(s["satisfaction"] * (s.get("num_sta", 0) or 0) for s in wt) / sta_total)
    elif wt:
        wifi_pct = round(sum(s["satisfaction"] for s in wt) / len(wt))
    else:
        wifi_pct = 100
    wifi_bad = wifi_pct < HEALTH_BAD_PCT
    # Detailed Wi-Fi quality: the average per-client experience score (0-100).
    exp = [c.get("wifi_experience_score") for c in clients
           if not c.get("is_wired") and c.get("wifi_experience_score")]
    wifi_exp_text = f"{round(sum(exp) / len(exp))}/100" if exp else "—"

    # --- Data usage: yesterday + rolling 30-day total, both from the daily report
    # (the aggregated dashboard only covers a 24h window, no monthly counter).
    yesterday_bytes, rolling_bytes, prev_bytes = _usage_from_daily(raw.get("daily"))
    if yesterday_bytes is None:  # report unavailable -> 24h WAN total from the dashboard
        summary = _dig(dash, "wan_activity", "activity_by_network_group", "WAN", "summary",
                       default={})
        yesterday_bytes = (summary.get("rx_bytes", 0) or 0) + (summary.get("tx_bytes", 0) or 0)
    # Usage trend: the last 30 days vs the 30 before them (more/less data overall).
    usage_trend = _pct_change(rolling_bytes, prev_bytes)

    return {
        # Title health figures (name + percentage); units drawn by the renderer.
        "isp_name": isp_name, "isp_pct": isp_pct, "isp_bad": isp_bad, "isp_trend": None,
        "wifi_pct": wifi_pct, "wifi_bad": wifi_bad, "wifi_trend": None,
        "wifi_exp_text": wifi_exp_text,
        # Detail rows: numeric strings only — the renderer appends the unit.
        "latency_val": str(latency_ms), "latency_trend": None,
        "usage_hier": _gb(yesterday_bytes), "usage_mois": _gb(rolling_bytes),
        "usage_trend": usage_trend,
        "iot": _network(clients, ssids["iot"], ssids["iot"] or "IoT"),
        "main": _network(clients, ssids["main"], ssids["main"] or "Perso"),
        # Raw values snapshotted by attach() to compute the 7-day trends.
        "_snap": {
            "usage_bytes": yesterday_bytes,
            "latency_ms": latency_ms, "isp_pct": isp_pct, "wifi_pct": wifi_pct,
        },
    }


def compute_trend(vals: list) -> float | None:
    """Latest completed day vs the average of the prior days, in %.

    `vals` is newest-first (latest, then up to TREND_DAYS prior). Returns None
    until at least two completed days exist."""
    if len(vals) < 2:
        return None
    latest, prior = vals[0], vals[1:]
    baseline = sum(prior) / len(prior)
    if not baseline:
        return None
    return round((latest - baseline) / baseline * 100)


def _pct_change(new: float, old: float) -> float | None:
    """Percent change of `new` vs `old`, or None when there's no baseline to
    compare against (old is zero/missing — e.g. a fresh install)."""
    if not old:
        return None
    return round((new - old) / old * 100)


def _usage_from_daily(daily, today=None) -> tuple[int | None, int, int]:
    """(yesterday, last-30-day total, previous-30-day total) WAN tx+rx bytes from
    the daily.gw report.

    yesterday is None when the report is unavailable (caller falls back). Both
    totals are full ROLLING_DAYS windows: the last sums the 30 complete days
    ending yesterday (today excluded, so always a full window — unlike a calendar
    month that collapses on the 1st); the previous sums the 30 before that (days
    -60..-31), giving the panel a 30-vs-30 trend. The previous total is 0 (→ no
    trend) when the report doesn't reach that far back."""
    rows = (daily or {}).get("data") if isinstance(daily, dict) else None
    if not rows:
        return None, 0, 0
    today = today or datetime.now(PARIS_TZ).date()
    yesterday = today - timedelta(days=1)
    last_start = today - timedelta(days=ROLLING_DAYS)          # -30 .. -1 (yesterday)
    prev_start = today - timedelta(days=2 * ROLLING_DAYS)      # -60 ..
    prev_end = today - timedelta(days=ROLLING_DAYS + 1)        #     .. -31
    y_bytes: int | None = None
    last_total = 0
    prev_total = 0
    for row in rows:
        ts = row.get("time")
        if ts is None:
            continue
        day = datetime.fromtimestamp(ts / 1000, PARIS_TZ).date()
        day_bytes = int((row.get("wan-tx_bytes", 0) or 0) + (row.get("wan-rx_bytes", 0) or 0))
        if day == yesterday:
            y_bytes = day_bytes
        if last_start <= day <= yesterday:
            last_total += day_bytes
        elif prev_start <= day <= prev_end:
            prev_total += day_bytes
    return y_bytes, last_total, prev_total
