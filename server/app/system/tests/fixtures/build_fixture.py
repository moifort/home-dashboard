"""Turn the seeded `build_dashboard_data` output into the full render fixture.

The seeded DB drives the DB-backed slices (Linky core, solar, cumulus, water),
but crypto and UniFi need live network credentials we don't have in tests. This
mirrors `scripts/gen_preview.py` (the panels it injects + its ALERTS_DEMO block):
inject representative crypto/UniFi snapshots, force a believable mix of
triggering values, then recompute the alert board so the rendered fixture
exercises *every* panel. The result is serialised to `dashboard_data.json`, the
frozen input of the layer-2 render golden.
"""
from app.alerts import build_board


def apply_demo_panels(data: dict) -> dict:
    """Inject the network-only panels + demo alert values onto a built data dict.

    Mutates and returns `data`. Keeps the same values as gen_preview.py so the
    golden reflects the current preview the user reviews in server/scripts/preview.png.
    """
    # UniFi: needs live gateway credentials → representative snapshot (SSID names
    # Atchoum / Iotchoum, matching the device).
    data.setdefault("unifi", {
        "isp_name": "Free", "isp_pct": 100, "isp_bad": False, "isp_trend": None,
        "wifi_pct": 99, "wifi_bad": False, "wifi_trend": None,
        "wifi_exp_text": "99/100",
        "latency_val": "2", "latency_trend": 12.0,
        "usage_hier": "18,0", "usage_mois": "117,5", "usage_trend": 8.0,
        "iot": {"label": "Iotchoum", "count": 13, "top": [
            ("Salon 8d:f7", "0,5"), ("Cuisine 8a:8b", "0,5"), ("Chambre Minipc…", "0,4"),
            ("Bureau 7c:2a", "0,3"), ("Entrée 3f:91", "0,2"), ("Capteur 2b:14", "0,1"),
            ("Caméra 6b:22", "0,1")]},
        "main": {"label": "Atchoum", "count": 2, "top": [
            ("MacBookPro Tibo", "15,5"), ("MacBookPro Lam…", "3,4")]},
    })

    # Crypto: needs live API credentials → representative banner + grid snapshot.
    data.setdefault("crypto", {
        "pct_text": "+12", "profit_positive": True,
        "profit_text": "+$1 234", "portfolio_text": "$11 234",
        "alpha_text": "+5", "alpha_positive": True, "sandbox": False,
    })
    if "crypto_grid" not in data:
        # The dip to 94 800 leaves the grid: the line is cut on the lower bound
        # and picks back up when the price returns, never flattened onto the axis.
        _grid_prices = [98000, 99500, 101000, 100200, 95500, 94800,
                        99500, 102000, 101200, 100500, 101800, 101500]
        data["crypto_grid"] = {
            "lower": 96000.0, "upper": 104000.0, "levels": 8,
            "current_price": 101500.0, "current_price_text": "$101 500",
            "points": [(i, float(p)) for i, p in enumerate(_grid_prices)],
            # Validated cycles, on grid levels: two winners (black), one loser (red).
            "cycles": [
                {"time": 1.5, "price": 100571.4, "profit": 11.2},
                {"time": 7.4, "price": 101714.3, "profit": 9.8},
                {"time": 10.2, "price": 102857.1, "profit": -4.5},
            ],
            "skips": [{"price": 97000.0, "side": "buy", "kind": "insufficient_funds"}],
        }

    # Force a believable mix of problems (red) and positive notes (black) so the
    # top-left Alertes panel renders populated, then recompute the board.
    data.setdefault("stats", {})
    data["stats"]["avg_kwh_pct"] = 15      # EDF bad: Conso ▲15%/j
    data["stats"]["hc_ratio_pct"] = -14    # EDF bad: Heures creuses ▼14%
    # Eau bad: leak — lower the average and spike the last finished (non-today) day.
    data.setdefault("water_stats", {})
    data["water_stats"]["avg_text"] = "120"
    for d in reversed(data.get("water_days", [])):
        if not d.get("today") and d.get("liters"):
            d["liters"] = 360             # -> Eau: Fuite ▲240L
            break
    # Solaire good (black): strong production rise — clear the real 0-kWh outage.
    data.setdefault("production_stats", {})
    data["production_stats"]["avg_kwh_pct"] = 45   # -> Solaire: Production ▲45%
    data["production_stats"]["savings_eur"] = 8.4  # -> économie 8,40 €
    for d in reversed(data.get("production_days", [])):
        if not d.get("today"):
            d["pv_kwh"] = 1.5
            break
    # Cumulus good (black): strong drop — override the seeded sensor's trend.
    for s in data.get("power_sensors", []):
        if s.get("name", "").lower() == "cumulus":
            s["trend_pct"] = -28                   # -> Cumulus: Conso ▼28%
            break

    data["alert_board"] = build_board(data)
    return data
