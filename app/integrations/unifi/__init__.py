"""UniFi network-quality slice.

Self-contained vertical slice: the REST transport lives in client.py, and below
the orchestration that turns the gateway payloads into the render-ready "Réseau"
panel (internet/Wi-Fi quality, clients per SSID, top-3 clients per network, data
usage). Fetched live on the hourly refresh; a tiny daily snapshot table
(daily_unifi) feeds the ▲▼ trends (7-day average, no backfill — history starts at
first connection). Remove the whole folder to drop the panel.
"""
import logging
import os
from datetime import datetime, timedelta

from app import db
from app.config import PARIS_TZ

from .client import fetch_unifi

logger = logging.getLogger(__name__)

HOST = os.environ.get("UNIFI_HOST", "https://192.168.1.1").rstrip("/")
USERNAME = os.environ.get("UNIFI_USERNAME", "")
PASSWORD = os.environ.get("UNIFI_PASSWORD", "")
SITE = os.environ.get("UNIFI_SITE", "default")
SSID_IOT = os.environ.get("UNIFI_SSID_IOT", "")
SSID_MAIN = os.environ.get("UNIFI_SSID_MAIN", "")

ENABLED = bool(PASSWORD)
HEALTH_BAD_PCT = 99  # internet/Wi-Fi quality below this reads as degraded (red)
TREND_DAYS = 7  # the latest completed day is compared to this many prior days
_last_unifi_time = ""

# Snapshot columns that carry a ▲▼ trend, paired with the panel key they fill.
_TREND_COLUMNS = (
    ("usage_bytes", "usage_trend"),
    ("latency_ms", "latency_trend"),
    ("isp_pct", "isp_trend"),
    ("wifi_pct", "wifi_trend"),
)


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_unifi snapshot table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_unifi (
            date TEXT PRIMARY KEY,
            usage_bytes REAL,
            speed_dl REAL,
            latency_ms REAL,
            isp_pct REAL,
            wifi_pct REAL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def start():
    """No background listener for UniFi."""
    return None


def attach(data: dict):
    """Fetch gateway stats, snapshot today's values, attach the panel + trends.

    On any failure the key is left unset, so the panel is simply omitted.
    """
    global _last_unifi_time
    raw = fetch_unifi(HOST, USERNAME, PASSWORD, SITE)
    if not raw:
        return
    panel = build_unifi_panel(raw, {"iot": SSID_IOT, "main": SSID_MAIN})
    if not panel:
        return
    _snapshot(panel.pop("_snap"))
    for column, key in _TREND_COLUMNS:
        panel[key] = _compute_trend(column)
    data["unifi"] = panel
    _last_unifi_time = datetime.now(PARIS_TZ).isoformat()


# --- Daily snapshot + 7-day trend (no backfill) ----------------------------

def _snapshot(snap: dict):
    """Store today's reading (one row/day; last refresh of the day wins)."""
    today = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")
    now = datetime.now(PARIS_TZ).isoformat()
    conn = db.connect()
    conn.execute(
        """INSERT OR REPLACE INTO daily_unifi
           (date, usage_bytes, latency_ms, isp_pct, wifi_pct, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (today, snap.get("usage_bytes"), snap.get("latency_ms"),
         snap.get("isp_pct"), snap.get("wifi_pct"), now),
    )
    conn.commit()
    conn.close()


def _compute_trend(column: str) -> float | None:
    """Latest completed day vs the average of up to TREND_DAYS prior days, in %.

    Returns None until at least two completed days exist (column is a fixed
    internal name, never user input)."""
    today = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")
    conn = db.connect()
    cur = conn.execute(
        f"SELECT {column} FROM daily_unifi "
        f"WHERE date < ? AND {column} IS NOT NULL ORDER BY date DESC LIMIT ?",
        (today, TREND_DAYS + 1),
    )
    vals = [r[0] for r in cur.fetchall()]
    conn.close()
    if len(vals) < 2:
        return None
    latest, prior = vals[0], vals[1:]
    baseline = sum(prior) / len(prior)
    if not baseline:
        return None
    return round((latest - baseline) / baseline * 100, 1)


# --- Raw payload -> render-ready panel --------------------------------------

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


def _short(name: str, limit: int = 15) -> str:
    name = (name or "?").strip()
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _client_bytes(c: dict) -> int:
    """Session traffic for a client (rx+tx); active-clients has no usage_bytes."""
    return int((c.get("rx_bytes", 0) or 0) + (c.get("tx_bytes", 0) or 0))


def _network(clients: list, ssid: str, label: str) -> dict:
    """Client count + top-3 by total traffic for one SSID (wireless only)."""
    members = [c for c in clients if not c.get("is_wired") and c.get("essid") == ssid]
    members.sort(key=_client_bytes, reverse=True)
    top = [
        (_short(c.get("display_name") or c.get("hostname") or c.get("mac", "?")),
         _gb(_client_bytes(c)))
        for c in members[:3]
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

    # --- Data usage: yesterday + current-month total, both from the daily report
    # (the aggregated dashboard only covers a 24h window, no monthly counter).
    yesterday_bytes, month_bytes = _usage_from_daily(raw.get("daily"))
    if yesterday_bytes is None:  # report unavailable -> 24h WAN total from the dashboard
        summary = _dig(dash, "wan_activity", "activity_by_network_group", "WAN", "summary",
                       default={})
        yesterday_bytes = (summary.get("rx_bytes", 0) or 0) + (summary.get("tx_bytes", 0) or 0)

    return {
        # Title health figures (name + percentage); units drawn by the renderer.
        "isp_name": isp_name, "isp_pct": isp_pct, "isp_bad": isp_bad, "isp_trend": None,
        "wifi_pct": wifi_pct, "wifi_bad": wifi_bad, "wifi_trend": None,
        "wifi_exp_text": wifi_exp_text,
        # Detail rows: numeric strings only — the renderer appends the unit.
        "latency_val": str(latency_ms), "latency_trend": None,
        "usage_hier": _gb(yesterday_bytes), "usage_mois": _gb(month_bytes), "usage_trend": None,
        "iot": _network(clients, ssids["iot"], "IoT"),
        "main": _network(clients, ssids["main"], "Perso"),
        # Raw values snapshotted by attach() to compute the 7-day trends.
        "_snap": {
            "usage_bytes": yesterday_bytes,
            "latency_ms": latency_ms, "isp_pct": isp_pct, "wifi_pct": wifi_pct,
        },
    }


def _usage_from_daily(daily) -> tuple[int | None, int]:
    """(yesterday, current-month total) WAN tx+rx bytes from the daily.gw report.

    yesterday is None when the report is unavailable (caller falls back); the
    month total is the running sum of every day in the current month (today
    included, partial)."""
    rows = (daily or {}).get("data") if isinstance(daily, dict) else None
    if not rows:
        return None, 0
    today = datetime.now(PARIS_TZ).date()
    yesterday = today - timedelta(days=1)
    y_bytes: int | None = None
    month_total = 0
    for row in rows:
        ts = row.get("time")
        if ts is None:
            continue
        day = datetime.fromtimestamp(ts / 1000, PARIS_TZ).date()
        day_bytes = int((row.get("wan-tx_bytes", 0) or 0) + (row.get("wan-rx_bytes", 0) or 0))
        if day == yesterday:
            y_bytes = day_bytes
        if (day.year, day.month) == (today.year, today.month):
            month_total += day_bytes
    return y_bytes, month_total


def status() -> dict:
    return {"unifi_enabled": ENABLED, "last_unifi": _last_unifi_time}
