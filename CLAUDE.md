# Dashboard e-Paper — Development Guide

## Architecture
- **project root**: Python Docker server (CasaOS, port 5000) that fetches Linky data, renders the dashboard bitmap with **Pillow** (`renderer.py` → `ImageDraw`, no browser), converts it to the 4-color EPD buffer (`converter.py`), and serves it at `/display` for the ESP32 to pull

## e-Paper Display

- **Model**: Waveshare 10.85" **(G) 4-color** (black, white, yellow, red)
- **Driver**: `epd10in85g` — NEVER `epd10in85` (B/W), different init sequence
- **Resolution**: 1360×480, 2 bits/pixel, buffer = 163,200 bytes
- **ESP32 IP**: variable (scan with `arp -a | grep esp32`)

## ESP32 Firmware (esp32-display/)

### Hardware
- **Board**: Seeed XIAO ESP32S3
- **HAT**: Waveshare 10.85inch e-Paper HAT+ — connect via its **10-pin labeled connector** (not the 40-pin RPi header)

### Pin Mapping (XIAO ↔ HAT+ 10-pin connector)

| HAT+ label | XIAO pin |
|------------|----------|
| VCC        | 3V3      |
| GND        | GND      |
| DIN        | D9       |
| CLK        | D8       |
| CS_M       | D2       |
| CS_S       | D10      |
| DC         | D1       |
| RST        | D0       |
| BUSY       | D3       |
| PWR        | D4       |

### Build & Flash

Requires [Arduino CLI](https://arduino.github.io/arduino-cli/) with `esp32:esp32` core:

```bash
brew install arduino-cli
arduino-cli core install esp32:esp32
```

```bash
# Compile (PSRAM=opi is mandatory — ps_malloc fails without it)
arduino-cli compile --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" esp32-display/

# Flash (port may vary — check with: ls /dev/cu.usb*)
arduino-cli upload --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" --port /dev/cu.usbmodem101 esp32-display/

# Serial monitor
arduino-cli monitor --port /dev/cu.usbmodem101 --config baudrate=115200
```

### BUSY Pin
- **HIGH** = ready, **LOW** = busy
- ReadBusy has a 60s timeout to prevent hangs

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
- **After any UI change, regenerate `docs/preview.png` and open it in the macOS Preview app** (`open -a Preview docs/preview.png`) so the user can review the result

## Git Workflow

- **Never `git push` automatically** — push only when the user says "push"
- On push: review local commits (`git log --oneline origin/main..HEAD`), squash reverts/serial fixes, clean up history
- Suggest pushing when good progress is made or a milestone is reached
- Commit after each verified change, but push is a deliberate act

### Pre-push docs & quality checklist (run EVERY push)

Before pushing, verify and update as needed:
- **CHANGELOG.md** — an entry exists for every user-facing change in the push.
- **README.md** — features, readings, endpoints and the **Optional** env setup blocks are complete and accurate (every new integration documented).
- **`docker-compose.yml` + `docker-compose.casaos.yml`** — every new env var is declared (empty default = disabled), ports/volumes correct, image/labels valid.
- **`.env.example`** — every new env var present with a helpful comment.
- **`docs/preview.png`** — regenerated when the rendered layout changed.
- **Environment variables** — if the push adds/renames env vars, tell the user which ones to add or fill on their CasaOS deployment.


## Linky / Conso API

- **API**: `conso.boris.sh/api/consumption_load_curve` (30-min intervals, in W)
- **PRM**: stored in `.env` (`LINKY_PRM`) — NEVER in code
- **Token**: JWT valid 3 years, stored in `.env` (`LINKY_TOKEN`) — NEVER in code
- **API limit**: max 7 days per request (8 days → 400 Bad Request)
- **HC/HP**: two off-peak windows — 23:32-5:32 (night) + 15:02-17:02 (afternoon), configurable via `HC_WINDOWS`
- **Pricing**: HP=0.2065 €/kWh, HC=0.1579 €/kWh, subscription=15.65 €/month

## EcoFlow PowerStream / Solar (optional)

- **Goal**: daily solar production (kWh/day) chart in the **top 50%** of the screen, above the Linky chart. Full-black single bars (no split), same title+separator style. Shows the **last 9 completed days** (today excluded; N/A if no data). Stats: avg kWh/day + trend (rising = good = black, falling = red), plus period total.
- **Data source**: the official Developer API (HMAC) exposes only instantaneous PV watts; the per-day energy counter (`254_32`) exists only on the **private app MQTT** but arrives on the device's own slow, non-forceable timer. So we read the **inverter heartbeat** power and integrate it ourselves into daily kWh.
- **Power read**: protobuf heartbeat `cmd_func=20 / cmd_id=1` → `PowerStreamInverterHeartbeat`; PV watts = `(pv1_input_watts + pv2_input_watts) / 10` (deci-watts). Integrated in `server._on_solar_power` into the `daily_production` table.
- **Keep-alive**: the device only publishes while polled. Re-publish a get-quota request (`build_get_quota_request`, cmd 20/1, src=dest=32) to `/app/{userId}/{sn}/thing/property/get` every 60s — otherwise it goes silent.
- **Auth flow**: `POST https://{host}/auth/login` (password base64, `scene=IOT_APP`) → token + userId; `GET /iot-auth/app/certification` → MQTT url/port/account/password (broker `mqtt-e.ecoflow.com:8883`). **TLS needs `certifi.where()`** or the handshake fails (macOS python.org / Docker slim).
- **No backfill**: history starts at first connection — EcoFlow cannot return past days.
- **Config**: `ECOFLOW_EMAIL`, `ECOFLOW_PASSWORD`, `ECOFLOW_DEVICE_SN`, `ECOFLOW_API_HOST` (default `api-e.ecoflow.com`). Integration is disabled (Linky-only) if any is missing.

## Crypto Bot panel (optional)

- **Goal**: an inline **title-style banner** in the empty **top-right** space (same look as the chart title banners — segments + 1px separator), on the same row as the solar chart's title. Leads with a `Crypto` label, then % return (black if profit ≥ 0, **red if < 0**), `±$profit`, `$portfolio`, and a `SANDBOX` badge. `renderer._draw_crypto_banner` reuses `_draw_stats_bar`.
- **Data source**: the crypto-bot's GraphQL API (`query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode } }`). `% = totalProfitUsdc / sommeMiseUsdc * 100`; portfolio = `sommeMiseUsdc + totalProfitUsdc`. Client in `crypto_client.py`.
- **Refresh on pull**: data is fetched **when the ESP32 calls `/display`** (it wakes only ~2×/day), re-rendering the buffer with fresh crypto; Linky/solar stay on the hourly cache. Any failure falls back to the cached hourly buffer (panel omitted).
- **Networking**: the dashboard runs in `network_mode: bridge`, so it reaches the co-located bot via its **LAN IP** (`http://192.168.1.50:3003/graphql`), not `localhost`.
- **Thousands separator**: use a plain space — Arial.ttf renders U+202F (the iOS widget's narrow no-break space) as a tofu box on e-paper.
- **Config**: `CRYPTO_API_URL` (empty = disabled), `CRYPTO_API_TOKEN` (the bot's `NITRO_API_TOKEN`, optional).

## Cumulus (water heater) consumption (optional)

- **Goal**: a **title-style banner** spanning the chart width, left-aligned at the very **bottom of the screen, below the EDF chart** (the consumption chart is shrunk by `CUMULUS_BANNER_H` to make room; its 1px separator sits *above* the text as a divider from the day labels), showing the water-heater's consumption: `Cumulus  <yesterday> kWh hier  <avg> kWh/j`. The value is **yesterday's** completed daily total (not today's partial one). `renderer._draw_cumulus_banner` reuses `_draw_stats_bar`.
- **Device**: the `cumulus` Zigbee device is a **Legrand 412171 DIN contactor**. It exposes `state`, `power` (W), `power_apparent` (VA) — **no energy (kWh) counter**. So we **integrate the reported power** into daily kWh ourselves (same technique as EcoFlow solar, `server._on_cumulus_power` → `daily_cumulus` table). No backfill — history starts at first connection.
- **Data source**: the Zigbee2MQTT broker (mosquitto). Subscribe to `zigbee2mqtt/cumulus`, read `power` from the JSON. The contactor publishes on change; we also re-request it (`{"power":""}` on `zigbee2mqtt/cumulus/get`) every 60s so integration keeps getting samples during steady heating. Client in `cumulus_client.py`.
- **Networking**: dashboard is in `network_mode: bridge`, so it reaches the broker via its **LAN IP** (`192.168.1.50:1883`), anonymous (no MQTT auth configured in Z2M).
- **Config**: `CUMULUS_MQTT_HOST` (empty = disabled), `CUMULUS_MQTT_PORT` (1883), `CUMULUS_TOPIC` (`zigbee2mqtt/cumulus`), `CUMULUS_MQTT_USERNAME`/`PASSWORD` (optional).

