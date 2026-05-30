"""Render docs/preview.png from local DB data + live crypto, for UI review.

Usage: python3 scripts/gen_preview.py
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

# Pull the real grid from the bot for the preview unless already configured.
os.environ.setdefault("CRYPTO_API_URL", "http://192.168.1.50:3003/graphql")
os.environ.setdefault("CRYPTO_API_TOKEN", "***REMOVED***")

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
        "iot": {"label": "IoT", "count": 13, "top": [
            ("Salon 8d:f7", "0,5"), ("Cuisine 8a:8b", "0,5"), ("Chambre Minipc…", "0,4")]},
        "main": {"label": "Perso", "count": 4, "top": [
            ("MacBookPro Tibo", "15,5"), ("MacBookPro Lam…", "3,4"), ("iPhone Tibo", "0,8")]},
    }

print("days:", len(data.get("days", [])),
      "| solar:", len(data.get("production_days", [])),
      "| crypto:", bool(data.get("crypto")),
      "| grid:", bool(data.get("crypto_grid")),
      "| cumulus:", bool(data.get("cumulus")))

out = ROOT / "docs" / "preview.png"
render_dashboard(data).save(str(out))
print("saved", out)
