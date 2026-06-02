# Dashboard — Panneau « Alertes » (design)

Date : 2026-06-02
Statut : validé pour implémentation

## Objectif

Ajouter, sous le panneau « Home » (gouttière gauche, ~192 px de large), une
section **Alertes** qui signale en rouge les anomalies métier détectées à partir
des tendances journalières déjà calculées par chaque intégration. Une alerte =
un triangle plein `▲` rouge suivi d'un texte court (1 ligne), tout en rouge
(`RED = (255, 0, 0)`, détecté par le convertisseur 4-couleurs : `r>180 & g<100 & b<100`).
Quand rien ne se déclenche, on affiche une ligne discrète noire **« Tout va bien »**.

## Contraintes & décisions

- **Source de détection** : uniquement les valeurs/tendances journalières déjà
  présentes dans le dict `data` (pas de données horaires — elles ne sont pas
  stockées aujourd'hui). Aucune nouvelle plomberie de capture.
- **Formulation** : concise, 1 ligne, qui tient dans ~192 px (≈ 26–30 caractères
  à Arial 13 px).
- **État « aucune alerte »** : titre « Alertes » + ligne « Tout va bien » (noir).
- **Police / rendu** : Arial, ▲ (triangle plein, jamais ↑↓), texte rouge pour
  les alertes, titre de section en noir gras. Positions arrondies (`round`).

## Architecture (approche A — moteur central)

Nouveau module `app/alerts.py` :

```python
# Chaque règle est une fonction pure (data) -> str | None : elle retourne le
# texte de l'alerte si son seuil est franchi, sinon None. Elle se protège
# par data.get(...) : si l'intégration source est absente (slice supprimée),
# la règle ne se déclenche jamais.

SEVERITY = {...}  # priorité de tri par clé de règle

def build_alerts(data: dict) -> list[dict]:
    """Exécute toutes les règles activées, retourne une liste triée
    [{"text": "▲ ...", "severity": int}, ...] (vide si RAS)."""
```

- `build_dashboard_data` (dans `app/dashboard_data.py`) appelle `build_alerts(data)`
  **après** que toutes les intégrations ont fait `attach()`, et pose
  `data["alerts"] = build_alerts(data)`.
- Le renderer reçoit `data["alerts"]` et le dessine ; il ne contient aucune logique
  métier.

Pourquoi central plutôt que par-slice : la garde `data.get(...)` donne déjà le
comportement « supprimer une intégration = supprimer ses alertes » sans étendre
l'API de slice ; les alertes sont transverses (tri/priorité communs) et tous les
seuils restent au même endroit, faciles à régler.

### Activation par règle

Chaque règle a un flag booléen (constante en tête de module, ex.
`RULE_ELEC_RISE = True`). Le cœur (1–5) est activé par défaut ; les règles
optionnelles (6–10) sont implémentées et activées mais triviales à couper en
passant le flag à `False`.

## Règles & seuils

Seuils = constantes nommées en tête de `app/alerts.py`.

| # | Clé | Déclencheur | Champ(s) data | Seuil | Message |
|---|-----|-------------|---------------|-------|---------|
| 1 | `elec_rise` | Conso EDF en hausse | `stats.avg_kwh_pct` | ≥ +10 % | `▲ Conso EDF +{pct}%/j` |
| 2 | `hc_drop` | Heures creuses en baisse | `stats.hc_ratio_pct` | ≤ −10 (points) | `▲ Heures creuses −{abs}%` |
| 3 | `water_leak` | Fuite d'eau probable | `water_days` (dernier jour terminé), `water_stats.avg_text` | jour > 2× moyenne **et** excès > 150 L | `▲ Fuite d'eau ? +{excess} L` |
| 4 | `solar_off` | Solaire déconnecté | `production_days` (hier, jour terminé) | hier = 0 kWh | `▲ Solaire HS ? 0 kWh hier` |
| 4b | `solar_drop` | Solaire en chute | `production_stats.avg_kwh_pct` | ≤ −30 % | `▲ Solaire −{abs}%` |
| 5 | `net_usage` | Forte conso Internet | `unifi.usage_trend` | ≥ +30 % | `▲ Internet +{pct}%/j` |
| 6 | `isp_bad` | Internet dégradé/HS | `unifi.isp_bad`, `unifi.isp_pct` | `isp_bad` vrai **ou** `isp_pct` < 95 | `▲ Internet dégradé {pct}%` |
| 7 | `latency` | Latence élevée | `unifi.latency_val` (int parse) | > 50 ms | `▲ Latence {ms} ms` |
| 8 | `wifi_bad` | WiFi dégradé | `unifi.wifi_bad`, `unifi.wifi_pct` | `wifi_bad` vrai **ou** `wifi_pct` < 90 | `▲ WiFi dégradé {pct}%` |
| 9 | `talon_rise` | Veille (talon) en hausse | `talon.trend_pct` | ≥ +25 % | `▲ Veille +{pct}%` |
| 10 | `cumulus_rise` | Cumulus en hausse | `cumulus.trend_pct` | ≥ +25 % | `▲ Cumulus +{pct}%` |

Notes de calcul :
- Les `*_pct` sont déjà arrondis par les intégrations ; on les affiche tels quels
  (valeur absolue pour les baisses, le `−` est dans le libellé).
- **Solaire HS** : on regarde le dernier jour *terminé* (avant-dernier élément de
  `production_days`, car le dernier est « aujourd'hui » partiel). Si `solar_off`
  se déclenche, on **n'émet pas** aussi `solar_drop` (éviter le doublon).
- **Fuite d'eau** : `water_stats.avg_text` est une chaîne (« 153 » ou « N/A ») →
  parser en float, ignorer si « N/A ». Dernier jour terminé = dernier `water_days`
  avec `today` faux et `liters` non nul. `excess = round(jour − moyenne)`.
- **Latence / pourcentages UniFi** : `latency_val`, `isp_pct`, `wifi_pct`,
  `usage_trend` — `usage_trend` peut être `None` (moins de 2 jours d'historique) →
  ignorer si `None`. `latency_val` est une chaîne → parser, ignorer si vide.

## Tri / priorité

Gravité décroissante : pannes & santé (`isp_bad`, `solar_off`, `water_leak`,
`wifi_bad`, `latency`) avant les hausses de tendance (`elec_rise`, `net_usage`,
`solar_drop`, `hc_drop`, `talon_rise`, `cumulus_rise`). Affichage plafonné à
**8 lignes** (la colonne en a la place) ; surplus ignoré (cas rare). Le plafond
est une constante `MAX_ALERTS = 8`.

## Rendu

Nouvelle fonction `_draw_alerts_panel(draw, fonts, alerts, region_top)` dans
`app/rendering/renderer.py`, appelée juste après `_draw_home_panel` et positionnée
sous lui (le panneau Home renverra son `y` de bas, ou on réutilise un offset fixe
calculé identiquement).

- Largeur = `PANEL_LEFT - CHART_LEFT - COL_GAP` (≈ 192 px), `x = CHART_LEFT`.
- Titre **Alertes** (gras, noir) + séparateur 1px (réutilise `_draw_stats_bar`
  avec un seul item, comme le panneau Home).
- Puis une ligne par alerte : `▲ ` + texte, tout en `RED`, police « regular »
  (poids ≥ 400). Pitch vertical = même `row_h` que le panneau Home.
- Si `alerts` vide : une ligne « Tout va bien » en noir « regular ».
- Le panneau ne dépasse pas le bas d'écran (`HEIGHT - CHART_BOTTOM`) ; le plafond
  `MAX_ALERTS` garantit qu'on n'écrit pas hors zone.

`_draw_home_panel` est modifié pour **retourner** le `y` du bas de son contenu,
afin que la section Alertes s'ancre dessous avec un petit écart (ex. +10 px).

## Données injectées par le preview

`scripts/gen_preview.py` injecte déjà des valeurs représentatives (talon, unifi,
water, cumulus). Pour visualiser des alertes dans le preview, on forcera quelques
valeurs déclenchantes (ex. `stats.avg_kwh_pct = 15`, un jour d'eau anormal) **dans
le script de preview uniquement**, sans toucher la logique de prod. Un second
rendu (ou un toggle) montrera l'état « Tout va bien ».

## Hors périmètre (v1)

- Détection fine horaire (fuite nocturne continue, panne solaire en temps réel) —
  nécessiterait de capturer/stocker des données infra-journalières.
- Alertes Crypto (non demandées).
- Historisation / accusé de réception des alertes (purement instantané, recalculé
  à chaque refresh).
- Configuration des seuils par variable d'env (constantes en dur pour la v1 ;
  pourra évoluer).

## Fichiers touchés

- **Nouveau** `app/alerts.py` — moteur + règles + seuils.
- `app/dashboard_data.py` — appel `build_alerts(data)` en fin de
  `build_dashboard_data`.
- `app/rendering/renderer.py` — `_draw_alerts_panel`, `_draw_home_panel` renvoie
  son bas, appel dans `render_dashboard`.
- `scripts/gen_preview.py` — valeurs déclenchantes pour la revue visuelle.
- (Au push uniquement) `CHANGELOG.md`, `README.md`.
