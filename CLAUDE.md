# Dashboard e-Paper — Development Guide

## Architecture

- **ESP32** (XIAO ESP32-S3): WiFi server on port 80, receives EPD binary buffer via `POST /display` or returns status via `GET /status`
- **project root**: Python Docker server (CasaOS, port 5000) that fetches Linky data, renders the HTML dashboard via Playwright, serves EPD buffer to ESP32 in pull mode (`GET /display`)

## e-Paper Display

- **Model**: Waveshare 10.85" **(G) 4-color** (black, white, yellow, red)
- **Driver**: `epd10in85g` — NEVER `epd10in85` (B/W), different init sequence
- **Resolution**: 1360×480, 2 bits/pixel, buffer = 163,200 bytes
- **ESP32 IP**: variable (scan with `arp -a | grep esp32`)

## e-Paper Rendering Rules (CRITICAL)

### Font
- **Arial only**. Do not use Inter, Cozette, Courier New, Aldrich, or any web/bitmap font — they all render worse after B&W thresholding
- `font-weight` minimum **400** (regular). NEVER 300 (light) — thin strokes disappear
- `font-weight` **700** (bold) for important values/numbers
- `font-variant-numeric: tabular-nums` for digits (uniform width)
- Day labels in **lowercase** (`text-transform: lowercase`) — uppercase letters have irregular spacing in Arial

### Rendering
- **NEVER** use `device_scale_factor` or any downscaling. Always render at native **1360×480**
- Required Chromium flags: `--disable-lcd-text --disable-font-subpixel-positioning --font-render-hinting=none`
- **NEVER use yellow for text or bars** — illegible (not enough contrast)
- Red (`#ff0000`) only for negative progressions (4color converter detects `r > 180 && g < 100 && b < 100`)
- Symbols: **▲▼** (filled triangles), never ↑↓ (too thin, invisible)

### Layout
- **flex** for all alignments, `align-items: center` for vertical alignment
- Left/center/right distribution: `justify-content: space-between` on parent, **without** `flex: 1` on children
- Separator lines at **1px** (not 2px)
- **`Math.round()`** on all JS-computed positions — sub-pixel values cause blur after thresholding
- No HTML spaces between spans — they shift alignment
- To align a banner with the chart: use `getBoundingClientRect()` in JS
- **Never** modify existing chart styles when adding surrounding elements

### Workflow
- After every template change, **analyze the rendered PNG** before sending to ESP32
- Check: alignment with separator line, text sharpness, digit spacing

## Git Workflow

- **Never `git push` automatically** — push only when the user says "push"
- On push: review local commits (`git log --oneline origin/main..HEAD`), squash reverts/serial fixes, clean up history, update README if needed
- Suggest pushing when good progress is made or a milestone is reached
- Commit after each verified change, but push is a deliberate act

## Linky / Conso API

- **API**: `conso.boris.sh/api/consumption_load_curve` (30-min intervals, in W)
- **PRM**: stored in `.env` (`LINKY_PRM`) — NEVER in code
- **Token**: JWT valid 3 years, stored in `.env` (`LINKY_TOKEN`) — NEVER in code
- **API limit**: max 7 days per request (8 days → 400 Bad Request)
- **HC/HP**: two off-peak windows — 23:32-5:32 (night) + 15:02-17:02 (afternoon), configurable via `HC_WINDOWS`
- **Pricing**: HP=0.2065 €/kWh, HC=0.1579 €/kWh, subscription=15.65 €/month
- **Architecture**: pull mode — ESP32 calls `GET /display` to retrieve pre-rendered buffer
