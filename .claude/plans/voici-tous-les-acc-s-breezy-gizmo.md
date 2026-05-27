# Plan : Police Inter + retour au point décimal

## Context

Les chiffres sur le dashboard e-paper ont un espacement irrégulier avec Arial (police proportionnelle). Les hacks CSS (`tabular-nums`, `letter-spacing`) aident partiellement. La solution propre est d'utiliser **Inter**, une police conçue pour la lisibilité écran avec des chiffres tabulaires natifs.

De plus, revenir au point décimal "." au lieu de la virgule "," (le changement précédent).

## Fichiers à modifier

### 1. `templates/dashboard.html`

- Charger Inter depuis Google Fonts : `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap">`
- Remplacer `font-family: Arial, Helvetica, sans-serif` par `font-family: 'Inter', Arial, sans-serif`
- Retirer le `.replace('.', ',')` sur les valeurs des barres
- Garder `font-variant-numeric: tabular-nums` (Inter le supporte nativement)

### 2. Aucun autre fichier modifié

## Commit prévu

1. `style(linky-server): use Inter font for better e-paper rendering`

## Vérification

1. Render et envoyer à l'ESP32
2. Vérifier l'espacement uniforme des chiffres
3. Vérifier la lisibilité des labels et du bandeau stats
4. Comparer visuellement avec le rendu Arial précédent
