# Plan : Dashboard conso électrique — e-Paper

## Context

Le pipeline web→e-paper est fonctionnel (Playwright + converter + ESP32). Le feedback du premier design : seuls les **bar charts CSS** (style Analytics box) rendent bien sur le e-paper. Les polices vectorielles (Inter, Silkscreen) sont floues après threshold car Chromium force l'anti-aliasing.

**Objectif :** Un écran dédié à la consommation électrique de la maison sur 7 jours, basé sur le style bar chart qui marche.

## Problème des polices — solution 2x

Les navigateurs forcent l'anti-aliasing sur tout le texte. Impossible à désactiver via CSS.

**Solution : rendre à 2720×960 (2x), downscaler en nearest-neighbor, puis threshold.**

- Playwright screenshot à 2720×960 (viewport `device_scale_factor: 2`)
- Pillow `resize((1360, 480), Image.NEAREST)` — nearest-neighbor préserve les bords nets
- Puis threshold classique → buffer EPD

Cela élimine le flou car chaque pixel anti-aliasé à 2x devient un pixel net à 1x.

## Design : Conso électrique 7 jours

Ultra-minimaliste. Juste les barres, les jours, et les kWh. Rien d'autre.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│                                                                          │
│   ██                                                                     │
│   ██  ██                          ██                                     │
│   ██  ██  ██              ██  ██  ██                                     │
│   ██  ██  ██  ██      ██  ██  ██  ██                                     │
│   ██  ██  ██  ██  ██  ██  ██  ██  ██                                     │
│   ██  ██  ██  ██  ██  ██  ██  ██  ██                                     │
│  Wed Thu Fri Sat Sun Mon Tue                                             │
│  18.2 16.5 15.1 12.8 9.4 14.3 12.4                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

**Éléments (strict minimum) :**
- 7 barres noires pleines, largeur égale, espacement régulier, occupent toute la largeur
- Label jour (3 lettres) sous chaque barre
- Valeur kWh sous le label jour
- C'est tout. Pas de titre, pas de stats, pas de lignes de grille

## Fichiers à modifier

### 1. `converter.py` — ajouter le downscale 2x
```python
def png_to_epd_buffer(png_bytes, mode="bw", dither="none"):
    img = Image.open(BytesIO(png_bytes))
    # Si rendu à 2x, downscaler en nearest-neighbor
    if img.size == (WIDTH * 2, HEIGHT * 2):
        img = img.resize((WIDTH, HEIGHT), Image.NEAREST)
    ...
```

### 2. `server.py` — viewport 2x
```python
page = browser.new_page(viewport={"width": 1360, "height": 480}, device_scale_factor=2)
```
Le screenshot sera automatiquement 2720×960. Le converter downscale.

### 3. `templates/dashboard.html` — nouveau template conso électrique
- Layout pleine largeur, centré sur le bar chart
- CSS rectangles pour les barres (pas de canvas nécessaire)
- Police monospace système (`Courier New`, `monospace`) qui est bitmap-friendly
- Données via `window.__DASHBOARD_DATA__` (pour l'instant, données statiques de test)
- Toutes couleurs pures `#000` / `#fff`
- Pas de border-radius (pixels nets)
- Bordures de 2px minimum (visible à 133 PPI)

## Données de test (statiques pour l'instant)

```javascript
window.__DASHBOARD_DATA__ = {
  days: [
    { day: "Wed", kwh: 18.2 },
    { day: "Thu", kwh: 16.5 },
    { day: "Fri", kwh: 15.1 },
    { day: "Sat", kwh: 12.8 },
    { day: "Sun", kwh: 9.4 },
    { day: "Mon", kwh: 14.3 },
    { day: "Tue", kwh: 12.4 }
  ],
  today_kwh: 12.4,
  week_total: 98.7,
  avg_kwh: 14.1
};
```

## Vérification

- [ ] `python3 server.py --once --save-png --esp32 192.168.1.73` fonctionne
- [ ] Le screenshot `last_render.png` est à 2720×960 (2x)
- [ ] Les polices sont nettes après conversion (pas de pixels gris parasites)
- [ ] Les barres sont bien proportionnées sur le e-paper
- [ ] Les labels jour/kWh sont lisibles

## Fichiers existants réutilisés

- `web_dashboard/server.py` — orchestrateur existant (modifier viewport)
- `web_dashboard/converter.py` — ajouter downscale NEAREST
- `web_dashboard/templates/dashboard.html` — remplacer par nouveau design
- `esp32-display/src/main.cpp` — aucun changement (même buffer 163,200 bytes)
