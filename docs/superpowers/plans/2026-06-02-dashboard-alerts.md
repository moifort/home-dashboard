# Panneau « Alertes » — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une section « Alertes » sous le panneau « Home » (gouttière gauche, ~192 px) qui affiche en rouge `▲` les anomalies métier détectées depuis les tendances journalières, ou « Tout va bien » quand il n'y en a aucune.

**Architecture:** Moteur central `app/alerts.py` = liste de règles pures `(data) -> str | None`, gardées par `data.get(...)`. `build_dashboard_data` pose `data["alerts"]` après les `attach()`. Le renderer dessine `data["alerts"]` via `_draw_alerts_panel`, sans logique métier.

**Tech Stack:** Python 3, Pillow (ImageDraw). Pas de framework de test : vérification via `scripts/gen_preview.py` + analyse du PNG `docs/preview.png` (convention du projet).

**Spec:** `docs/superpowers/specs/2026-06-02-dashboard-alerts-design.md`

---

## Structure de fichiers

- **Créer** `app/alerts.py` — moteur + 11 règles + seuils + tri/plafond.
- **Modifier** `app/dashboard_data.py` — appel `build_alerts(data)` en fin de `build_dashboard_data`.
- **Modifier** `app/rendering/renderer.py` — `_draw_alerts_panel` (nouveau), `_draw_home_panel` renvoie son bas, appel dans `render_dashboard`.
- **Modifier** `scripts/gen_preview.py` — valeurs déclenchantes (preview only) + recalcul des alertes avant rendu.

Notes de rendu (rappel CLAUDE.md) : Arial, `▲` triangle plein, texte rouge `RED=(255,0,0)` (détecté par le convertisseur 4-couleurs), titre noir gras, positions `round`. On utilise le signe ASCII `-` (pas U+2212) pour les baisses.

---

### Task 1 : Créer le moteur d'alertes `app/alerts.py`

**Files:**
- Create: `app/alerts.py`

- [ ] **Step 1 : Écrire le module complet**

Créer `app/alerts.py` avec exactement ce contenu :

```python
"""Trend-based alert engine for the top-left "Alertes" panel.

Each rule is a pure function (data) -> str | None: it returns a concise alert
message when its threshold is crossed, else None. Every rule guards on
data.get(...) so a removed integration (its data key absent) simply never
fires — no slice API to extend. build_alerts() runs every enabled rule, sorts
by severity (outages/health before trends) and caps the list; the renderer
only draws the result. Thresholds are the named constants below — tune here.
"""

# --- Thresholds (tune here) ---
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

MAX_ALERTS = 8            # cap on displayed alerts

# Per-rule enable flags. Core (1-5) on; optional (6-10) on but trivial to cut.
ENABLED = {
    "elec_rise": True,
    "hc_drop": True,
    "water_leak": True,
    "solar_off": True,
    "solar_drop": True,
    "net_usage": True,
    "isp_bad": True,
    "latency": True,
    "wifi_bad": True,
    "talon_rise": True,
    "cumulus_rise": True,
}

# Severity: higher = more urgent, shown first. Outages/health before trends.
SEVERITY = {
    "isp_bad": 100,
    "solar_off": 95,
    "water_leak": 90,
    "wifi_bad": 80,
    "latency": 70,
    "elec_rise": 50,
    "net_usage": 45,
    "solar_drop": 40,
    "hc_drop": 35,
    "talon_rise": 20,
    "cumulus_rise": 15,
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


# --- Rules: each returns the bare message (no marker) or None ---

def _elec_rise(data):
    pct = (data.get("stats") or {}).get("avg_kwh_pct")
    if pct is not None and pct >= ELEC_RISE_PCT:
        return f"Conso EDF +{round(pct)}%/j"
    return None


def _hc_drop(data):
    pct = (data.get("stats") or {}).get("hc_ratio_pct")
    if pct is not None and pct <= -HC_DROP_PTS:
        return f"Heures creuses -{round(abs(pct))}%"
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
        return f"Fuite d'eau ? +{round(last - avg)} L"
    return None


def _solar_off(data):
    finished = [d for d in (data.get("production_days") or []) if not d.get("today")]
    if finished and finished[-1].get("pv_kwh", 0) == 0:
        return "Solaire HS ? 0 kWh hier"
    return None


def _solar_drop(data):
    # Suppressed when solar_off already fired (avoid a duplicate).
    if _solar_off(data) is not None:
        return None
    pct = (data.get("production_stats") or {}).get("avg_kwh_pct")
    if pct is not None and pct <= -SOLAR_DROP_PCT:
        return f"Solaire -{round(abs(pct))}%"
    return None


def _net_usage(data):
    pct = (data.get("unifi") or {}).get("usage_trend")
    if pct is not None and pct >= NET_USAGE_RISE_PCT:
        return f"Internet +{round(pct)}%/j"
    return None


def _isp_bad(data):
    unifi = data.get("unifi") or {}
    if not unifi:
        return None
    pct = unifi.get("isp_pct")
    has_pct = isinstance(pct, (int, float))
    if unifi.get("isp_bad") or (has_pct and pct < ISP_PCT_MIN):
        return f"Internet dégradé {round(pct)}%" if has_pct else "Internet dégradé"
    return None


def _latency(data):
    ms = _to_float((data.get("unifi") or {}).get("latency_val"))
    if ms is not None and ms > LATENCY_MS_MAX:
        return f"Latence {round(ms)} ms"
    return None


def _wifi_bad(data):
    unifi = data.get("unifi") or {}
    if not unifi:
        return None
    pct = unifi.get("wifi_pct")
    has_pct = isinstance(pct, (int, float))
    if unifi.get("wifi_bad") or (has_pct and pct < WIFI_PCT_MIN):
        return f"WiFi dégradé {round(pct)}%" if has_pct else "WiFi dégradé"
    return None


def _talon_rise(data):
    pct = (data.get("talon") or {}).get("trend_pct")
    if pct is not None and pct >= TALON_RISE_PCT:
        return f"Veille +{round(pct)}%"
    return None


def _cumulus_rise(data):
    pct = (data.get("cumulus") or {}).get("trend_pct")
    if pct is not None and pct >= CUMULUS_RISE_PCT:
        return f"Cumulus +{round(pct)}%"
    return None


_RULES = [
    ("elec_rise", _elec_rise),
    ("hc_drop", _hc_drop),
    ("water_leak", _water_leak),
    ("solar_off", _solar_off),
    ("solar_drop", _solar_drop),
    ("net_usage", _net_usage),
    ("isp_bad", _isp_bad),
    ("latency", _latency),
    ("wifi_bad", _wifi_bad),
    ("talon_rise", _talon_rise),
    ("cumulus_rise", _cumulus_rise),
]


def build_alerts(data: dict) -> list[dict]:
    """Run every enabled rule, sort by severity (desc), cap at MAX_ALERTS.

    Returns a list of {"text": "▲ ...", "severity": int, "key": str}; empty when
    nothing fires. A rule that raises is treated as 'no alert' — a render must
    never crash on a malformed value.
    """
    alerts = []
    for key, rule in _RULES:
        if not ENABLED.get(key, False):
            continue
        try:
            msg = rule(data)
        except Exception:
            msg = None
        if msg:
            alerts.append({"text": f"▲ {msg}", "severity": SEVERITY.get(key, 0), "key": key})
    alerts.sort(key=lambda a: a["severity"], reverse=True)
    return alerts[:MAX_ALERTS]
```

- [ ] **Step 2 : Vérifier que le module se charge et se comporte**

Run:
```bash
cd /Users/thibaut/Code/dashboard && python3 -c "
from app.alerts import build_alerts
# RAS -> liste vide
print('vide:', build_alerts({}))
# Quelques déclencheurs
data = {
  'stats': {'avg_kwh_pct': 15, 'hc_ratio_pct': -14},
  'unifi': {'isp_pct': 100, 'isp_bad': False, 'wifi_pct': 99, 'wifi_bad': False,
            'latency_val': '78', 'usage_trend': 42.0},
  'water_stats': {'avg_text': '120'},
  'water_days': [{'liters': 360, 'today': False}, {'liters': 64, 'today': True}],
}
for a in build_alerts(data):
    print(a['severity'], a['text'])
"
```
Expected (ordre par gravité décroissante) :
```
vide: []
90 ▲ Fuite d'eau ? +240 L
70 ▲ Latence 78 ms
50 ▲ Conso EDF +15%/j
45 ▲ Internet +42%/j
35 ▲ Heures creuses -14%
```

- [ ] **Step 3 : Commit**

```bash
cd /Users/thibaut/Code/dashboard
git add app/alerts.py
git commit -m "feat(alerts): trend-based alert engine (rules + thresholds)"
```

---

### Task 2 : Brancher le moteur dans la couche données

**Files:**
- Modify: `app/dashboard_data.py`

- [ ] **Step 1 : Importer le moteur**

Dans `app/dashboard_data.py`, remplacer la ligne d'import des intégrations :

```python
from app.integrations import OPTIONAL, linky
```

par :

```python
from app import alerts as alerts_engine
from app.integrations import OPTIONAL, linky
```

- [ ] **Step 2 : Calculer les alertes après les `attach()`**

Toujours dans `app/dashboard_data.py`, remplacer la fin de `build_dashboard_data` :

```python
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    return data
```

par :

```python
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    # Alerts run last so every integration's trends are already attached.
    data["alerts"] = alerts_engine.build_alerts(data)
    return data
```

- [ ] **Step 3 : Vérifier l'assemblage**

Run:
```bash
cd /Users/thibaut/Code/dashboard && DB_PATH="$PWD/.data/linky.db" python3 -c "
from app import dashboard_data, db
from app.integrations import linky
linky.init_schema()
data = dashboard_data.build_dashboard_data(db.get_cached_days('2000-01-01','2100-01-01'))
print('alerts key present:', 'alerts' in data, '| count:', len(data.get('alerts', [])))
"
```
Expected : `alerts key present: True | count: <un entier ≥ 0>` (pas d'exception).

- [ ] **Step 4 : Commit**

```bash
cd /Users/thibaut/Code/dashboard
git add app/dashboard_data.py
git commit -m "feat(alerts): compute data[\"alerts\"] after integrations attach"
```

---

### Task 3 : Dessiner le panneau « Alertes » dans le renderer

**Files:**
- Modify: `app/rendering/renderer.py` (3 endroits : `_draw_home_panel` renvoie son bas ; nouveau `_draw_alerts_panel` ; appel dans `render_dashboard`)

- [ ] **Step 1 : Faire renvoyer au panneau Home le `y` de son bas**

Dans `app/rendering/renderer.py`, `_draw_home_panel` se termine actuellement par :

```python
    y = sep_y + 6
    row([("Mise à jour", "regular", BLACK)], [(home.get("last_text", ""), "bold", BLACK)], y)
    y += row_h
    row([("Prochaine", "regular", BLACK)], [(home.get("next_text", ""), "bold", BLACK)], y)
```

Remplacer ce bloc par (ajoute un `return` du bas du contenu) :

```python
    y = sep_y + 6
    row([("Mise à jour", "regular", BLACK)], [(home.get("last_text", ""), "bold", BLACK)], y)
    y += row_h
    row([("Prochaine", "regular", BLACK)], [(home.get("next_text", ""), "bold", BLACK)], y)
    return y + line_h  # bottom of the panel content (for the Alerts panel below)
```

Et changer la signature/docstring de `_draw_home_panel` : remplacer

```python
def _draw_home_panel(draw, fonts, home, region_top) -> None:
```

par

```python
def _draw_home_panel(draw, fonts, home, region_top) -> int:
```

- [ ] **Step 2 : Ajouter `_draw_alerts_panel` juste après `_draw_home_panel`**

Insérer cette fonction immédiatement après la fin de `_draw_home_panel` (avant `_draw_unifi_panel`) :

```python
def _draw_alerts_panel(draw, fonts, alerts, region_top) -> None:
    """Draw the "Alertes" panel in the top-left gutter, under the Home panel: a
    title banner (1px separator, like Home) then one concise red ▲ line per
    alert, or a discreet black "Tout va bien" when there is none. Capped by the
    screen bottom so it never writes out of the region."""
    width = PANEL_LEFT - CHART_LEFT - COL_GAP
    x = CHART_LEFT

    line_h = draw.textbbox((0, 0), "Xg", font=fonts["bold"])[3]
    row_h = line_h + 3

    sep_y = region_top + draw.textbbox((0, 0), "X", font=fonts["bold"])[3] + 8
    _draw_stats_bar(draw, fonts, [[("Alertes", "bold", BLACK)]], x, region_top, width, sep_y)

    y = sep_y + 6
    if not alerts:
        draw.text((x, y), "Tout va bien", fill=BLACK, font=fonts["regular"])
        return

    max_y = HEIGHT - CHART_BOTTOM - line_h
    for a in alerts:
        if y > max_y:
            break
        draw.text((x, y), a["text"], fill=RED, font=fonts["regular"])
        y += row_h
```

- [ ] **Step 3 : Appeler le panneau dans `render_dashboard`**

Dans `render_dashboard`, le bloc actuel est :

```python
    # "Home" panel in the empty top-left gutter (left of the packed columns):
    # a title banner over the last/next refresh times.
    home = data.get("home")
    if home:
        _draw_home_panel(draw, fonts, home, region_top=0)
```

Le remplacer par :

```python
    # "Home" panel in the empty top-left gutter (left of the packed columns):
    # a title banner over the last/next refresh times, then the "Alertes" panel
    # stacked just below it (same gutter).
    home = data.get("home")
    if home:
        home_bottom = _draw_home_panel(draw, fonts, home, region_top=0)
        _draw_alerts_panel(draw, fonts, data.get("alerts") or [], region_top=home_bottom + 10)
```

- [ ] **Step 4 : Vérifier que le rendu ne casse pas (smoke render)**

Run:
```bash
cd /Users/thibaut/Code/dashboard && python3 -c "
from app.rendering.renderer import render_dashboard
data = {
  'days': [], 'home': {'last_text': 'mar 11:34', 'next_text': '12:34'},
  'alerts': [{'text': '▲ Conso EDF +15%/j', 'severity': 50, 'key': 'elec_rise'},
             {'text': '▲ Latence 78 ms', 'severity': 70, 'key': 'latency'}],
}
img = render_dashboard(data)
print('rendered', img.size)
"
```
Expected : `rendered (1360, 480)` sans exception.

- [ ] **Step 5 : Commit**

```bash
cd /Users/thibaut/Code/dashboard
git add app/rendering/renderer.py
git commit -m "feat(alerts): draw the top-left Alertes panel under Home"
```

---

### Task 4 : Preview avec alertes déclenchées + revue visuelle

**Files:**
- Modify: `scripts/gen_preview.py`

- [ ] **Step 1 : Injecter des valeurs déclenchantes (preview only) et recalculer les alertes**

Dans `scripts/gen_preview.py`, le bloc final est actuellement :

```python
print("days:", len(data.get("days", [])),
      "| solar:", len(data.get("production_days", [])),
      "| crypto:", bool(data.get("crypto")),
      "| grid:", bool(data.get("crypto_grid")),
      "| cumulus:", bool(data.get("cumulus")))

out = ROOT / "docs" / "preview.png"
render_dashboard(data).save(str(out))
print("saved", out)
```

Insérer, **juste avant** la ligne `print("days:", ...)`, ce bloc de démonstration (les alertes sont recalculées car `build_dashboard_data` les avait figées avant nos injections représentatives) :

```python
# Preview only: force a representative set of triggering values so the
# top-left "Alertes" panel renders populated, then recompute the alerts (the
# build above ran before the unifi/water injections below). Set ALERTS_DEMO
# to False to preview the empty "Tout va bien" state instead.
from app.alerts import build_alerts  # noqa: E402

ALERTS_DEMO = True
if ALERTS_DEMO:
    data.setdefault("stats", {})
    data["stats"]["avg_kwh_pct"] = 15      # -> Conso EDF +15%/j
    data["stats"]["hc_ratio_pct"] = -14    # -> Heures creuses -14%
    data["unifi"]["latency_val"] = "78"    # -> Latence 78 ms
    data["unifi"]["usage_trend"] = 42.0    # -> Internet +42%/j
    # Water leak: lower the average and spike the last finished (non-today) day.
    data["water_stats"]["avg_text"] = "120"
    for d in reversed(data["water_days"]):
        if not d.get("today") and d.get("liters"):
            d["liters"] = 360              # -> Fuite d'eau ? +240 L
            break
data["alerts"] = build_alerts(data)
print("alerts:", [a["text"] for a in data["alerts"]])
```

- [ ] **Step 2 : Régénérer le preview**

Run:
```bash
cd /Users/thibaut/Code/dashboard && python3 scripts/gen_preview.py
```
Expected : une ligne `alerts: ['▲ Fuite d'eau ? +240 L', '▲ Latence 78 ms', '▲ Conso EDF +15%/j', '▲ Internet +42%/j', '▲ Heures creuses -14%']` puis `saved .../docs/preview.png`.

- [ ] **Step 3 : Analyser le PNG rendu (en haut à gauche)**

Lire `docs/preview.png` (outil Read) et vérifier dans le quart haut-gauche :
- Le panneau « Home » est intact (titre + 2 lignes + séparateur).
- En dessous, un titre « Alertes » avec son séparateur 1px.
- Une ligne **rouge** par alerte, chacune préfixée d'un `▲`, tenant sur une seule ligne sans déborder à droite (largeur ~192 px) ni chevaucher le graphique Solaire (qui commence à `PANEL_LEFT`).
- Texte net (pas d'antialiasing baveux), triangles pleins visibles.

Si une ligne déborde en largeur : raccourcir le libellé concerné dans `app/alerts.py` (Task 1) puis régénérer. Sinon continuer.

- [ ] **Step 4 : Ouvrir le preview pour revue utilisateur (workflow CLAUDE.md)**

Run:
```bash
open -a Preview /Users/thibaut/Code/dashboard/docs/preview.png
```

- [ ] **Step 5 : Vérifier l'état « Tout va bien »**

Éditer temporairement `scripts/gen_preview.py` : passer `ALERTS_DEMO = True` à `ALERTS_DEMO = False`, lancer `python3 scripts/gen_preview.py`, relire `docs/preview.png` et confirmer que le panneau affiche « Alertes » + « Tout va bien » (noir). **Puis remettre `ALERTS_DEMO = True`** et régénérer (le preview commité montre le panneau peuplé).

- [ ] **Step 6 : Commit**

```bash
cd /Users/thibaut/Code/dashboard
git add scripts/gen_preview.py docs/preview.png
git commit -m "feat(alerts): preview demo values for the Alertes panel"
```

---

### Task 5 : Documentation (au push uniquement)

> Conformément à la convention du projet, CHANGELOG/README ne sont mis à jour qu'au moment du `push`, pas pendant le développement.

- [ ] **Step 1 : Au prochain push, mettre à jour la doc**
  - `CHANGELOG.md` : entrée pour le panneau « Alertes » (détection par tendances, ▲ rouge, état « Tout va bien »).
  - `README.md` : décrire la section Alertes et la liste des règles/seuils dans la partie fonctionnalités.
  - Pas de nouvelle variable d'env (seuils en dur) → rien à ajouter dans `.env.example` / `docker-compose*.yml`.

---

## Self-review (auteur du plan)

- **Couverture spec :** moteur + 11 règles (Task 1) ✓ ; `data["alerts"]` après attach (Task 2) ✓ ; rendu panneau + état RAS + ancrage sous Home + plafond écran (Task 3) ✓ ; preview déclenché + revue visuelle + vérif RAS (Task 4) ✓ ; doc au push (Task 5) ✓.
- **Placeholders :** aucun — chaque étape contient le code/commande exacts.
- **Cohérence des types :** `build_alerts(data) -> list[dict]` avec clés `text`/`severity`/`key` ; le renderer lit `a["text"]` ; `_draw_home_panel -> int` consommé par `home_bottom`. Noms cohérents entre tâches.
- **Valeurs de vérif :** l'exemple Step 2 de Task 1 donne `+240 L` (360−120), seuils croisés (15≥10, −14≤−10, 78>50, 42≥30, leak), tri par gravité (90,70,50,45,35) — cohérent avec Task 4 Step 2.
