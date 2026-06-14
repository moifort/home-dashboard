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

from app import dashboard_data  # noqa: E402  (env must be set first)
from app.system.config import PARIS_TZ  # noqa: E402
from app import electricity, solar  # noqa: E402
from app.electricity import power  # noqa: E402
from app.electricity.infrastructure import repository as electricity_repo  # noqa: E402
from app.electricity.power import Sensor  # noqa: E402
from app.rendering.renderer import render_dashboard  # noqa: E402

# Apply pending schema migrations (e.g. the talon_w column) as the server does
# at startup, so reading from an older dev DB doesn't fail.
electricity.init_schema()

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
solar.ENABLED = "daily_production" in _tables
# Migrate any legacy single-device tables into daily_power, then drive the
# bottom power-sensor rows from the recommended Cumulus / Lave-linge config.
power.init_schema()
power.SENSORS = [
    Sensor("cumulus", "zigbee2mqtt/cumulus", "Cumulus"),
    Sensor("lave-linge", "zigbee2mqtt/lave-linge", "Lave-linge"),
]
power.ENABLED = bool(power.SENSORS)

now = datetime.now(PARIS_TZ)
start = (now - timedelta(days=45)).strftime("%Y-%m-%d")
# End is tomorrow (exclusive) so today's partial row feeds the live "Auj." bar,
# same window as the server's load_days().
end = (now + timedelta(days=1)).strftime("%Y-%m-%d")

days = electricity_repo.get_cached_days(start, end)
data = dashboard_data.build_dashboard_data(days)

# No live PTEC stream here; inject the full day's HC/HP windows so the Home
# panel shows all four tariff lines, grouped HC then HP (label once per group,
# blank on the second window — same as _attach_tariff).
data["home"].setdefault("tariff", [
    {"period": "HC", "start_text": "23:32", "end_text": "05:32"},
    {"period": "", "start_text": "13:00", "end_text": "15:00"},
    {"period": "HP", "start_text": "05:32", "end_text": "13:00"},
    {"period": "", "start_text": "17:02", "end_text": "23:32"},
])

# No device telemetry in the dev DB; inject a representative battery line so the
# Home panel shows the "Batt." autonomy row (days since the last charge).
data["home"].setdefault("battery", {
    "since_value": "4", "since_unit": "j", "since_text": "4j 6h",
    "avg_text": "4j 16h", "record_text": "5j 10h", "cycles": 3,
})

# The dev DB may hold no Linky history (build_core always emits the 9 calendar
# days, data or not); inject a representative EDF stacked HC/HP week whenever
# no complete day carries data so the preview shows a full consumption chart.
if not any(d["hc_kwh"] + d["hp_kwh"] > 0
           for d in data.get("days", []) if not d.get("today")):
    from app.system.config import DAYS_FR

    edf = [(5.1, 2.6), (4.2, 2.0), (5.6, 3.1), (4.9, 2.5), (6.0, 3.4),
           (3.8, 1.9), (5.2, 2.7), (4.5, 2.3),
           (1.6, 1.1)]  # (hc, hp) kWh; last = today, mid-day partial
    data["days"] = [
        {"day": DAYS_FR[(now.weekday() - (len(edf) - 1 - i)) % 7], "date": "",
         "hc_kwh": hc, "hp_kwh": hp, "today": i == len(edf) - 1}
        for i, (hc, hp) in enumerate(edf)
    ]
    data["stats"] = {"avg_kwh": 7.4, "avg_kwh_pct": 3, "hc_ratio": 64,
                     "hc_ratio_pct": -2, "avg_price": 2.08, "avg_price_pct": 3}


# The intraday strips under the EDF bars need tic_samples history (the Lixee
# only accumulates going forward); inject a representative 48-slot PAPP profile
# on every day that lacks one — today's stays partial (cut at the current slot).
def _demo_profile(seed_i, last_slot=48):
    prof = []
    for slot in range(48):
        if slot >= last_slot:
            prof.append(None)
            continue
        hour = slot // 2
        base = 280 + (seed_i % 5) * 12
        if 7 <= hour < 9:
            v = base + 1500 + (slot % 3) * 250
        elif 12 <= hour < 14:
            v = base + 800 + (slot % 2) * 300
        elif 19 <= hour < 22:
            v = base + 2000 + (slot % 4) * 200
        else:
            v = base + (slot % 4) * 30
        prof.append(float(v))
    return prof


def _demo_solar_profile(seed_i, last_slot=48):
    """Representative PV daylight bell (mean W per 30-min slot, under 800 W)."""
    prof = []
    for slot in range(48):
        if slot >= last_slot:
            prof.append(None)
            continue
        prof.append(max(0.0, 760 - abs(slot - 27) * 55 - (seed_i % 4) * 40 - (slot % 3) * 12))
    return prof


def _demo_water_profile(seed_i, last_slot=48):
    """Representative litres per 30-min slot: morning / midday / evening usage."""
    prof = []
    for slot in range(48):
        if slot >= last_slot:
            prof.append(None)
            continue
        hour = slot // 2
        if 7 <= hour < 9:
            v = 9 + (slot % 3) * 3 + (seed_i % 4)
        elif 12 <= hour < 14:
            v = 4 + (slot % 2) * 3
        elif 19 <= hour < 22:
            v = 11 + (slot % 4) * 2 + (seed_i % 3) * 2
        else:
            v = 0
        prof.append(float(v))
    return prof


for i, d in enumerate(data.get("days", [])):
    if not d.get("intraday"):
        last = now.hour * 2 + (1 if now.minute >= 30 else 0) if d.get("today") else 48
        d["intraday"] = _demo_profile(i, last)

# The dev DB may hold no solar history; inject a representative production week so
# the preview shows the center-bottom Solaire chart.
if not data.get("production_days"):
    from app.system.config import DAYS_FR

    pv = [3.1, 5.8, 6.4, 2.2, 7.1, 4.5, 6.9, 5.2, 1.4]  # kWh/day, last = today (partial)
    data["production_days"] = [
        {"day": DAYS_FR[(now.weekday() - (len(pv) - 1 - i)) % 7], "pv_kwh": v,
         "today": i == len(pv) - 1}
        for i, v in enumerate(pv)
    ]
    data["production_stats"] = {"avg_kwh": 5.3, "avg_kwh_pct": 8, "total_kwh": 67.2,
                                "savings_eur": 8.4, "talon_cover_pct": 111}

# The Solaire intraday strips need solar_samples history (accumulates going
# forward only); inject the demo bell on every day that lacks a profile —
# today's stays partial (cut at the current slot).
for i, d in enumerate(data.get("production_days", [])):
    if not d.get("intraday"):
        last = now.hour * 2 + (1 if now.minute >= 30 else 0) if d.get("today") else 48
        d["intraday"] = _demo_solar_profile(i, last)

# The dev DB may hold no power-sensor history; inject representative rows so the
# preview still shows the bottom Cumulus / Lave-linge rows the device renders.
if not data.get("power_sensors"):
    data["power_sensors"] = [
        {"name": "Cumulus", "yesterday_text": "2.4", "yesterday_unit": "kWh", "avg_text": "3.1",
         "avg_unit": "kWh/j", "trend_pct": 4.5, "hc_pct": 78,
         "spark": [3.4, 2.9, 3.1, 1.8, 3.0, 2.6, 2.4]},
        {"name": "Lave-linge", "yesterday_text": "0.8", "yesterday_unit": "kWh", "avg_text": "0.9",
         "avg_unit": "kWh/j", "trend_pct": -5.0, "hc_pct": 31,
         "spark": [0.9, 1.3, 0.7, None, 1.1, 0.6, 0.8]},
    ]

# Extra representative rows (appended, deduped by name) so the preview shows a
# fuller table: more rows, varied magnitudes (kWh and Wh), HC% spread.
_extra_sensors = [
    {"name": "Machine à laver", "yesterday_text": "1.1", "yesterday_unit": "kWh",
     "avg_text": "0.9", "avg_unit": "kWh/j", "avg_kwh": 0.9, "trend_pct": -5.0, "hc_pct": 72,
     "spark": [0.9, 1.3, 0.7, None, 1.1, 0.6, 1.1]},
    {"name": "Serveur", "yesterday_text": "2.9", "yesterday_unit": "kWh",
     "avg_text": "2.8", "avg_unit": "kWh/j", "avg_kwh": 2.8, "trend_pct": 1.2, "hc_pct": 35,
     "spark": [2.8, 2.7, 2.9, 2.8, 2.8, 2.9, 2.9]},
    {"name": "Salon", "yesterday_text": "640", "yesterday_unit": "Wh",
     "avg_text": "710", "avg_unit": "Wh/j", "avg_kwh": 0.71, "trend_pct": 8.3, "hc_pct": 22,
     "spark": [0.6, 0.8, 0.7, 0.9, 0.5, 0.8, 0.64]},
    {"name": "Imprimante 3D", "yesterday_text": "450", "yesterday_unit": "Wh",
     "avg_text": "380", "avg_unit": "Wh/j", "avg_kwh": 0.38, "trend_pct": -12.0, "hc_pct": 5,
     "spark": [0.2, None, 0.5, 0.4, 0.3, 0.6, 0.45]},
    # A >15-char name to exercise the bottom-table ellipsis truncation.
    {"name": "Imp. 3D, chargeurs, lampe", "yesterday_text": "520", "yesterday_unit": "Wh",
     "avg_text": "460", "avg_unit": "Wh/j", "avg_kwh": 0.46, "trend_pct": 6.0, "hc_pct": 12,
     "spark": [0.4, 0.5, None, 0.4, 0.6, 0.5, 0.52]},
]
_have = {s.get("name") for s in data.get("power_sensors", [])}
data["power_sensors"] += [s for s in _extra_sensors if s["name"] not in _have]

# The talon needs the new talon_w column populated (one fetch cycle). On a dev DB
# that predates it, inject representative values so the bottom Talon row shows.
if data.get("talon", {}).get("yesterday_text") in (None, "N/A", "—"):
    data["talon"] = {"yesterday_text": "318", "avg_text": "305", "avg_w": 305, "trend_pct": -4.0,
                     "spark": [298, 312, 305, 330, 321, 309, 318]}

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
            ("Salon 8d:f7", "0,5"), ("Cuisine 8a:8b", "0,5"), ("Chambre Minipc Bureau", "0,4"),
            ("Bureau 7c:2a", "0,3")]},
        "main": {"label": "Atchoum", "count": 4, "top": [
            ("MacBookPro Tibo", "15,5"), ("MacBookPro Lamia", "3,4"), ("iPhone Tibo", "0,8"),
            ("iPad Lamia", "0,6")]},
    }

# The water meter needs a live MQTT broker we don't have here; inject a
# representative 7-day history so the preview shows the top-center Eau chart.
if "water_days" not in data:
    from app.system.config import DAYS_FR

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

# The Eau intraday strips need water_samples history (accumulates going
# forward only); inject the demo usage pattern on every day that lacks a
# profile — today's stays partial (cut at the current slot).
for i, d in enumerate(data.get("water_days", [])):
    if not d.get("intraday"):
        last = now.hour * 2 + (1 if now.minute >= 30 else 0) if d.get("today") else 48
        d["intraday"] = _demo_water_profile(i, last)

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

# The Zigbee soil sensors need a live MQTT broker we don't have here; inject two
# representative plants (matching the golden seed) so the preview shows the
# left-gutter "Plantes" panel — Basilic's spark carries a gap (a missing day).
if "plants" not in data:
    data["plants"] = [
        {"name": "Ficus", "moisture_pct": 45, "moisture_text": "45",
         "temperature": 27.0, "temperature_text": "27", "illuminance_text": "76",
         "needs_water": True, "low_battery": True, "last_seen_text": "3h",
         "spark": [35, 40, 45, 50, 55, 30, 35, 40, 45, 42]},
        {"name": "Basilic", "moisture_pct": 61, "moisture_text": "61",
         "temperature": 24.0, "temperature_text": "24", "illuminance_text": "850",
         "needs_water": False, "low_battery": False, "last_seen_text": "5h",
         "spark": [49, 53, 57, None, 45, 49, 53, 57, 61, 58]},
    ]

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
    # Cumulus good (black): strong drop — override the Cumulus sensor's trend.
    # Also inject representative 7-day sparklines (the dev DB has no power history,
    # so the real series are empty) — one with a gap to show missing-day handling.
    _demo_spark = {
        "cumulus": [3.4, 2.9, 3.1, 1.8, 3.0, 2.6, 2.4],
        "lave-linge": [0.9, 1.3, 0.7, None, 1.1, 0.6, 0.8],
    }
    for s in data.get("power_sensors", []):
        name = s.get("name", "").lower()
        if name == "cumulus":
            s["trend_pct"] = -28                   # -> Cumulus: Conso ▼28%
        if not any(v is not None for v in (s.get("spark") or [])):
            s["spark"] = _demo_spark.get(name, [2.0, 2.4, 1.9, 2.6, 2.1, 2.3, 2.5])
data["alert_board"] = build_board(data)
print("board:", [(r["label"], [f"{m} {f} {mo}".strip() for m, f, mo, _ in r["items"]]
                              if r.get("alert") else "RAS")
                 for r in data["alert_board"]])

print("days:", len(data.get("days", [])),
      "| solar:", len(data.get("production_days", [])),
      "| crypto:", bool(data.get("crypto")),
      "| grid:", bool(data.get("crypto_grid")),
      "| power:", len(data.get("power_sensors", [])))

out = ROOT / "scripts" / "preview.png"
render_dashboard(data).save(str(out))
print("saved", out)
