"""Render server/scripts/preview.png from local DB data + live crypto, for UI review.

Usage (from the server/ directory): python3 scripts/gen_preview.py
Needs the local data DB (Linky/solar/cumulus history). Crypto is pulled live
when CRYPTO_API_URL/TOKEN are set in the environment (or defaulted below).
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point at the local DB (server defaults to the in-container /data path).
os.environ.setdefault("DB_PATH", str(ROOT / ".data" / "linky.db"))

# Pull the real grid from the bot for the preview: export CRYPTO_API_URL and
# CRYPTO_API_TOKEN before running (kept out of the repo). Without them the
# preview simply renders without the crypto panel.

from datetime import datetime  # noqa: E402

from app import dashboard_data, db  # noqa: E402  (env must be set first)
from app.config import PARIS_TZ  # noqa: E402
from app.integrations import cumulus, ecoflow, linky  # noqa: E402
from app.rendering.renderer import render_dashboard  # noqa: E402

# Apply pending schema migrations (e.g. the talon_w column) as the server does
# at startup, so reading from an older dev DB doesn't fail.
linky.init_schema()

# Show panels backed by cached DB history even though their live integrations
# need credentials we don't have here. Only enable those whose table exists in
# the local DB (older dev DBs may predate the cumulus table).
import sqlite3  # noqa: E402

_tables = {
    r[0]
    for r in sqlite3.connect(os.environ["DB_PATH"]).execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
}
ecoflow.ENABLED = "daily_production" in _tables
cumulus.ENABLED = "daily_cumulus" in _tables

now = datetime.now(PARIS_TZ)
start = (now - timedelta(days=45)).strftime("%Y-%m-%d")
end = now.strftime("%Y-%m-%d")

days = db.get_cached_days(start, end)
data = dashboard_data.build_dashboard_data(days)

# The dev DB may predate the cumulus table; inject a representative banner so
# the preview still shows the bottom Cumulus row the device renders.
if "cumulus" not in data:
    data["cumulus"] = {"yesterday_text": "2.4", "avg_text": "3.1", "trend_pct": 4.5}

# The talon needs the new talon_w column populated (one fetch cycle). On a dev DB
# that predates it, inject representative values so the bottom Talon row shows.
if data.get("talon", {}).get("yesterday_text") in (None, "N/A"):
    data["talon"] = {"yesterday_text": "318", "avg_text": "305", "avg_w": 305, "trend_pct": -4.0}

# The UniFi panel needs live gateway credentials we don't have here; inject a
# representative snapshot so the preview shows the bottom-right Réseau panel.
if "unifi" not in data:
    data["unifi"] = {
        "isp_name": "Free", "isp_pct": 100, "isp_bad": False, "isp_trend": None,
        "wifi_pct": 99, "wifi_bad": False, "wifi_trend": None,
        "wifi_exp_text": "99/100",
        "latency_val": "2", "latency_trend": 12.0,
        "usage_hier": "18,0", "usage_mois": "117,5", "usage_trend": 8.0,
        "iot": {"label": "Iotchoum", "count": 13, "top": [
            ("Salon 8d:f7", "0,5"), ("Cuisine 8a:8b", "0,5"), ("Chambre Minipc…", "0,4"),
            ("Bureau 7c:2a", "0,3")]},
        "main": {"label": "Atchoum", "count": 4, "top": [
            ("MacBookPro Tibo", "15,5"), ("MacBookPro Lam…", "3,4"), ("iPhone Tibo", "0,8"),
            ("iPad Lamia", "0,6")]},
    }

# The water meter needs a live MQTT broker we don't have here; inject a
# representative 7-day history so the preview shows the top-center Eau chart.
if "water_days" not in data:
    from app.config import DAYS_FR

    sample = [118, 142, 168, 95, 210, 130, None, 155, 64]  # last = today, mid-day partial
    data["water_days"] = [
        {"day": DAYS_FR[(now.weekday() - (len(sample) - 1 - i)) % 7], "liters": v,
         "today": i == len(sample) - 1}
        for i, v in enumerate(sample)
    ]
    data["water_stats"] = {
        "avg_text": "153", "avg_pct": -6.5,
        "month_total_text": "4.18", "cost_text": "16.30",
    }

# The crypto bot needs live API credentials (CRYPTO_API_URL/TOKEN) we don't
# have here; inject a representative banner + grid snapshot so the preview shows
# the top-right Crypto panel and its grid chart.
if "crypto" not in data:
    data["crypto"] = {
        "pct_text": "+12", "profit_positive": True,
        "profit_text": "+$1 234", "portfolio_text": "$11 234",
        "alpha_text": "+5", "alpha_positive": True, "sandbox": False,
    }
if "crypto_grid" not in data:
    _grid_prices = [98000, 99500, 101000, 100200, 99800, 100800,
                    102000, 101200, 100500, 101800, 102500, 101500]
    data["crypto_grid"] = {
        "lower": 96000.0, "upper": 104000.0, "levels": 8,
        "current_price": 101500.0, "current_price_text": "$101 500",
        "points": [(i, float(p)) for i, p in enumerate(_grid_prices)],
        "skips": [{"price": 97000.0, "side": "buy", "kind": "insufficient_funds"}],
    }

# Preview only: force a representative set of triggering values so the
# top-left "Alertes" panel renders populated, then recompute the alerts (the
# build above ran before the unifi/water injections below). Set ALERTS_DEMO
# to False to preview the empty "Tout va bien" state instead.
from app.alerts import build_board  # noqa: E402

ALERTS_DEMO = True
if ALERTS_DEMO:
    # A believable mix of problems (red) and positive notes (black): EDF + Eau
    # alert, Solaire + Cumulus show good trends, Réseau stays "ok".
    data.setdefault("stats", {})
    data["stats"]["avg_kwh_pct"] = 15      # EDF bad: Conso ▲15%/j
    data["stats"]["hc_ratio_pct"] = -14    # EDF bad: Heures creuses ▼14% (2nd EDF item)
    # Eau bad: leak — lower the average and spike the last finished (non-today) day.
    data["water_stats"]["avg_text"] = "120"
    for d in reversed(data["water_days"]):
        if not d.get("today") and d.get("liters"):
            d["liters"] = 360              # -> Eau: Fuite ▲240L
            break
    # Solaire good (black): strong production rise — clear the real 0-kWh outage.
    data.setdefault("production_stats", {})
    data["production_stats"]["avg_kwh_pct"] = 45   # -> Solaire: Production ▲45%
    data["production_stats"]["savings_eur"] = 8.4  # -> économie 8,40 €
    for d in reversed(data.get("production_days", [])):
        if not d.get("today"):
            d["pv_kwh"] = 1.5
            break
    # Cumulus good (black): strong drop.
    data["cumulus"]["trend_pct"] = -28             # -> Cumulus: Conso ▼28%
data["alert_board"] = build_board(data)
print("board:", [(r["label"], [f"{m} {f} {mo}".strip() for m, f, mo, _ in r["items"]]
                              if r.get("alert") else "RAS")
                 for r in data["alert_board"]])

print("days:", len(data.get("days", [])),
      "| solar:", len(data.get("production_days", [])),
      "| crypto:", bool(data.get("crypto")),
      "| grid:", bool(data.get("crypto_grid")),
      "| cumulus:", bool(data.get("cumulus")))

out = ROOT / "scripts" / "preview.png"
render_dashboard(data).save(str(out))
print("saved", out)
