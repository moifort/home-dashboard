"""Render every screen of the design board: one PNG per data scenario and UI.

Usage (from the server/ directory): python3 scripts/gen_board.py [out_dir]

Starts from the frozen render fixture (app/system/tests/fixtures/dashboard_data.json,
so the output is deterministic), applies one small mutation per scenario, recomputes
the alert board and renders the scenario with the classic UI, the matrice UI
(light, plus dark for the reference scenarios) and the arcade UI. The home lab
scenarios only exist in arcade, the one UI that shows it. The PNGs feed the
artboards of the "Home Dashboard Board" canvas; out_dir defaults to
.claude/board/project/img.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.alerts import build_board  # noqa: E402
from app.rendering.renderer import render_dashboard  # noqa: E402

FIXTURE = ROOT / "app" / "system" / "tests" / "fixtures" / "dashboard_data.json"
DEFAULT_OUT = ROOT.parent / ".claude" / "board" / "project" / "img"

OPTIONAL_KEYS = {
    "water": ("water_days", "water_stats"),
    "solar": ("production_days", "production_stats"),
    "crypto": ("crypto", "crypto_grid"),
    "network": ("unifi",),
    "plants": ("plants",),
    "power": ("power_sensors",),
    "homelab": ("homelab",),
}


def _drop(data, *domains):
    for dom in domains:
        for key in OPTIONAL_KEYS[dom]:
            data.pop(key, None)


def _last_finished(days):
    return next(d for d in reversed(days) if not d.get("today"))


def _quiet(data):
    """Bring every figure back under its alert threshold."""
    data["stats"].update(avg_kwh_pct=2, hc_ratio_pct=1)
    data["talon"]["trend_pct"] = -1
    data["water_stats"]["avg_text"] = "143"
    _last_finished(data["water_days"])["liters"] = 150
    data["production_stats"]["avg_kwh_pct"] = 4
    _last_finished(data["production_days"])["pv_kwh"] = 9.6
    for s in data["power_sensors"]:
        s["trend_pct"] = 2
        s["hc_pct"] = s["hc_pct_prev"] = 78
        s["yesterday_hc_kwh"] = round(s["yesterday_kwh"] * 0.8, 2)
    for p in data["plants"]:
        p.update(needs_water=False, low_battery=False, moisture_pct=62, moisture_text="62")
    data["unifi"].update(latency_trend=None, usage_trend=2.0)


def complet(data):
    pass


def tout_va_bien(data):
    _quiet(data)


def bonnes_nouvelles(data):
    _quiet(data)
    data["production_stats"]["record_kwh"] = 14.2


def alertes_max(data):
    data["talon"]["trend_pct"] = 24
    _last_finished(data["production_days"])["pv_kwh"] = 0
    data["unifi"].update(isp_bad=True, isp_pct=82, isp_trend=-18.0, wifi_bad=True, wifi_pct=71,
                         wifi_trend=-28.0, wifi_exp_text="71/100", latency_val="48",
                         latency_trend=140.0, usage_trend=65.0, new_clients=["ESP-4f:a2"])
    for p in data["plants"]:
        p.update(needs_water=True, low_battery=True, moisture_pct=12, moisture_text="12")


def electricite_seule(data):
    _drop(data, *OPTIONAL_KEYS)


def sans_crypto(data):
    _drop(data, "crypto")


def sans_solaire(data):
    _drop(data, "solar")


def sans_eau(data):
    _drop(data, "water")


def sans_reseau(data):
    _drop(data, "network")


def sans_prises_ni_plantes(data):
    _drop(data, "power", "plants")


def crypto_en_perte(data):
    data["crypto"].update(pct_text="-8", profit_positive=False, profit_text="-$812",
                          portfolio_text="$9 188", alpha_text="-3", alpha_positive=False)
    for c in data["crypto_grid"]["cycles"]:
        c["profit"] = -abs(c["profit"])


def crypto_sandbox(data):
    data["crypto"]["sandbox"] = True


def crypto_hors_grille(data):
    prices = [101000, 102200, 103400, 103900, 104800, 105600, 105100, 104300,
              103700, 104900, 106200, 106800]
    data["crypto_grid"].update(points=[[i, float(p)] for i, p in enumerate(prices)],
                               current_price=106800.0, current_price_text="$106 800",
                               skips=[])


def premier_jour(data):
    """Server just installed: only today's partial bar, no stats yet."""
    for key, field in (("days", ("hc_kwh", "hp_kwh")), ("production_days", ("pv_kwh",))):
        for d in data[key]:
            if not d.get("today"):
                d.update({f: 0 for f in field}, intraday=[None] * 48)
    for d in data["water_days"]:
        if not d.get("today"):
            d.update(liters=None, intraday=[None] * 48)
    data["stats"] = {"avg_kwh": None, "avg_kwh_pct": 0, "hc_ratio": None,
                     "hc_ratio_pct": 0, "avg_price": None, "avg_price_pct": 0}
    data["production_stats"] = {"avg_kwh": 0, "avg_kwh_pct": 0, "total_kwh": 3.1,
                                "savings_eur": 0.6, "autonomy_pct": None}
    data["water_stats"] = {"avg_text": "N/A", "avg_pct": 0, "month_total_text": "0.21",
                           "cost_text": "0.82"}
    data["talon"] = {"yesterday_text": "—", "avg_text": "—", "avg_w": None, "trend_pct": 0,
                     "annual_text": None, "cost_text": "—", "spark": [None] * 7}
    for s in data["power_sensors"]:
        s.update(avg_kwh=None, avg_text="N/A", cost_text="—", trend_pct=0, hc_pct=None,
                 hc_pct_prev=None, yesterday_kwh=None, yesterday_hc_kwh=None,
                 yesterday_text="—", spark=[None] * 7)
    for p in data["plants"]:
        p["spark"] = [None] * 9 + [p["moisture_pct"]]
    data["home"].pop("battery", None)
    data["home"]["net_cost"] = {"abo_text": "0", "mtd_text": "1", "proj_text": None}


def jours_manquants(data):
    """The server was down two days: those days stay blank on every chart."""
    for i in (3, 4):
        data["days"][i].update(hc_kwh=0, hp_kwh=0, intraday=[None] * 48)
        data["production_days"][i].update(pv_kwh=0, intraday=[None] * 48)
        data["water_days"][i].update(liters=None, intraday=[None] * 48)
    for s in data["power_sensors"]:
        s["spark"][2] = s["spark"][3] = None
    data["talon"]["spark"][2] = data["talon"]["spark"][3] = None


def debut_de_journee(data):
    """06:00 refresh: today's bars barely started."""
    for key in ("days", "production_days", "water_days"):
        today = data[key][-1]
        today["intraday"] = [v if i < 12 else None for i, v in enumerate(today["intraday"])]
    data["days"][-1].update(hc_kwh=1.1, hp_kwh=0.1)
    data["production_days"][-1]["pv_kwh"] = 0.0
    data["water_days"][-1]["liters"] = 6
    data["home"].update(last_text="06:00", next_text="08:00")


def batterie_faible(data):
    data["home"]["battery"].update(percent=4, since_value="5", since_text="5j 8h")


def beaucoup_de_prises(data):
    extra = [("Serveur", 2.8, "2.8", "kWh/j", "16", 1.2, 35),
             ("Machine à laver", 0.9, "900", "Wh/j", "4,7", -5.0, 72),
             ("Imprimante 3D", 0.38, "380", "Wh/j", "2,4", -12.0, 5),
             ("Imp. 3D, chargeurs, lampe", 0.46, "460", "Wh/j", "2,8", 6.0, 12)]
    for name, kwh, text, unit, cost, trend, hc in extra:
        data["power_sensors"].append({
            "name": name, "avg_kwh": kwh, "avg_text": text, "avg_unit": unit, "cost_text": cost,
            "trend_pct": trend, "hc_pct": hc, "hc_pct_prev": hc, "yesterday_kwh": kwh,
            "yesterday_hc_kwh": round(kwh * hc / 100, 2), "yesterday_text": text,
            "yesterday_unit": unit.split("/")[0],
            "spark": [round(kwh * f, 2) for f in (0.9, 1.2, 0.8, 1.0, 1.1, 0.7, 1.0)]})


def reseau_degrade(data):
    data["unifi"].update(isp_bad=True, isp_pct=82, isp_trend=-18.0, wifi_bad=True, wifi_pct=71,
                         wifi_trend=-28.0, wifi_exp_text="71/100", latency_val="48",
                         latency_trend=140.0, usage_trend=65.0)


def plantes_a_arroser(data):
    for p in data["plants"]:
        p.update(needs_water=True, low_battery=True, moisture_pct=14, moisture_text="14")
    data["plants"].append({
        "name": "Monstera", "moisture_pct": 9, "moisture_text": "9", "temperature": 21.0,
        "temperature_text": "21", "illuminance": 420.0, "illuminance_text": "420",
        "fertility": 11.0, "fertility_text": "11", "needs_water": True, "low_battery": False,
        "last_seen_text": "2h", "spark": [48, 44, 39, 35, 30, 26, 21, 17, 12, 9]})


def sans_home_lab(data):
    _drop(data, "homelab")


def pi_hors_ligne(data):
    """One Pi stopped answering six hours ago, another one runs hot."""
    down, hot = data["homelab"]["nodes"][1], data["homelab"]["nodes"][3]
    down.update(online=False, cpu=down["cpu"][:18] + [None] * 6, temp=down["temp"][:18] + [None] * 6)
    hot.update(temp_bad=True, temp=[t + 20 for t in hot["temp"]])


# (sub-section, [scenario, ...]); the reference scenarios also get the dark theme.
SECTIONS = [
    ("reference", [complet, tout_va_bien]),
    ("alertes", [bonnes_nouvelles, alertes_max]),
    ("domaines", [electricite_seule, sans_crypto, sans_solaire, sans_eau, sans_reseau,
                  sans_prises_ni_plantes]),
    ("crypto", [crypto_en_perte, crypto_sandbox, crypto_hors_grille]),
    ("electricite", [premier_jour, jours_manquants, debut_de_journee, batterie_faible,
                     beaucoup_de_prises]),
    ("reseau-plantes", [reseau_degrade, plantes_a_arroser]),
    ("homelab", [sans_home_lab, pi_hors_ligne]),
]
DARK = {"complet", "tout_va_bien"}
ARCADE_ONLY = {"sans_home_lab", "pi_hors_ligne"}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    base = json.loads(FIXTURE.read_text())
    for section, scenarios in SECTIONS:
        for scenario in scenarios:
            data = copy.deepcopy(base)
            scenario(data)
            data["alert_board"] = build_board(data)
            name = scenario.__name__.replace("_", "-")
            variants = [("classic", None), ("matrice", "light")]
            if scenario.__name__ in DARK:
                variants.append(("matrice", "dark"))
            if scenario.__name__ in ARCADE_ONLY:
                variants = []
            variants.append(("arcade", None))
            for ui, theme in variants:
                suffix = ui if theme is None else f"{ui}-{theme}"
                render_dashboard(data, ui=ui, theme=theme).save(out / f"{name}-{suffix}.png")
            alerts = [f"{r['label']}:{len(r['items'])}" for r in data["alert_board"]]
            print(f"{section:15} {name:24} alertes={alerts or 'aucune'}")


if __name__ == "__main__":
    main()
