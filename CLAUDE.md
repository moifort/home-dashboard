# Dashboard e-Paper — Guide de développement

## Architecture

- **ESP32** (XIAO ESP32-S3) : serveur WiFi sur port 80, reçoit un buffer EPD binaire via `POST /display` ou retourne son statut via `GET /status`
- **linky-server/** : serveur Python Docker (CasaOS, port 5000) qui fetch les données Linky, rend le dashboard HTML via Playwright, sert le buffer EPD à l'ESP32 en mode pull (`GET /display`)
- **web_dashboard/** : pipeline de rendu alternatif (HTML → Playwright screenshot → converter → ESP32)
- **main.py** : dashboard Raspberry Pi avec rendu direct SPI (pas lié au linky-server)

## Écran e-Paper

- **Modèle** : Waveshare 10.85" **(G) 4 couleurs** (noir, blanc, jaune, rouge)
- **Driver** : `epd10in85g` — JAMAIS `epd10in85` (B/W), séquence d'init différente
- **Résolution** : 1360×480, 2 bits/pixel, buffer = 163 200 octets
- **ESP32 IP** : variable (scanner avec `arp -a | grep esp32`)

## Règles de rendu e-Paper (CRITIQUE)

### Police
- **Arial uniquement**. Ne pas utiliser Inter, Cozette, Courier New, ni aucune police web/bitmap — toutes rendent moins bien après seuillage B&W
- `font-weight` minimum **400** (regular). JAMAIS 300 (light) — les traits fins disparaissent
- `font-weight` **700** (bold) pour les valeurs/chiffres importants
- `font-variant-numeric: tabular-nums` pour les chiffres (largeur uniforme)
- Labels de jours en **lowercase** (`text-transform: lowercase`) — les majuscules ont un espacement irrégulier en Arial

### Rendu
- **JAMAIS** de `device_scale_factor` ni de downscale. Toujours rendu natif **1360×480**
- Flags Chromium obligatoires : `--disable-lcd-text --disable-font-subpixel-positioning --font-render-hinting=none`
- **JAMAIS de jaune pour du texte ou des barres** — illisible (pas assez de contraste)
- Rouge (`#ff0000`) uniquement pour les progressions négatives (le converter 4color détecte `r > 180 && g < 100 && b < 100`)
- Symboles : **▲▼** (triangles pleins), jamais ↑↓ (trop fins, invisibles)

### Layout
- **flex** pour tous les alignements, `align-items: center` pour l'alignement vertical
- Distribution gauche/centre/droite : `justify-content: space-between` sur le parent, **sans** `flex: 1` sur les enfants
- Lignes de séparation en **1px** (pas 2px)
- **`Math.round()`** sur toutes les positions calculées en JS — les valeurs sub-pixel causent du flou
- Pas d'espace HTML entre les spans — ça décale l'alignement
- Pour aligner un bandeau avec le chart : `getBoundingClientRect()` en JS
- Ne **jamais** toucher au style du graphique existant quand on ajoute des éléments

### Workflow
- Après chaque modification du template, **analyser le PNG rendu** avant d'envoyer à l'ESP32
- Vérifier : alignement avec la ligne de séparation, netteté du texte, espacement des chiffres

## Git Workflow

- **Ne jamais `git push` automatiquement** — pousser uniquement quand l'utilisateur dit "push" ou "pousse"
- Quand on pousse : vérifier les commits locaux (`git log --oneline origin/main..HEAD`), squash les reverts/fix en série, nettoyer l'historique, mettre à jour le README si nécessaire
- Proposer de pousser quand on a bien avancé ou qu'un milestone est atteint
- Commit après chaque modification vérifiée, mais le push est un acte délibéré

## Linky / Conso API

- **API** : `conso.boris.sh/api/consumption_load_curve` (intervalles 30 min, en W)
- **PRM** : `REDACTED_PRM`
- **Token** : JWT 3 ans, stocké dans `.env` (`LINKY_TOKEN`) — JAMAIS dans le code
- **Limite API** : max 7 jours par requête (8 jours → 400 Bad Request)
- **HC/HP** : deux fenêtres HC — 23h32-5h32 (nuit) + 15h02-17h02 (après-midi), configurable via `HC_WINDOWS`
- **Tarifs** : HP=0.2065 €/kWh, HC=0.1579 €/kWh, abonnement=15.65 €/mois
- **Architecture** : pull mode — ESP32 appelle `GET /display` pour récupérer le buffer pré-rendu
