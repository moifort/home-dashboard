# Dashboard e-Paper — Development Guide

## Architecture
- **`app/` package**: Python Docker server (CasaOS, port 5000, run with `python -m app`) that fetches Linky data, renders the dashboard bitmap with **Pillow** (`app/rendering/renderer.py` → `ImageDraw`, no browser), converts it to the 4-color EPD buffer (`app/rendering/converter.py`), and serves it at `/display` for the ESP32 to pull

### Project structure (vertical slices)
```
app/
  __main__.py          # python -m app
  config.py            # global settings (paths, version, TZ, DB_PATH, PORT…)
  db.py                # SQLite primitive: connect() + daily-table accessors
  server.py            # HTTP server, refresh loop, /status assembled from slices
  dashboard_data.py    # orchestrator: Linky core + each enabled slice.attach()
  rendering/           # renderer.py + converter.py
  integrations/        # one self-contained folder per integration
    __init__.py        # OPTIONAL registry — drop a slice = delete folder + 1 line
    linky/   {api/, client.py, __init__.py}        # core
    ecoflow/ {client.py, mqtt/, proto/, __init__.py}
    cumulus/ {mqtt/, __init__.py}
    crypto/  {graphql/, __init__.py}
```
Each integration's `__init__.py` exposes the uniform slice API — `enabled()`,
`init_schema()`, `start()`, `attach(data)`, `status()` — and owns its env config,
DB table, power integrator and render panel. Tech-specific transport lives in a
subfolder (`mqtt/`, `proto/`, `graphql/`, `api/`). Removing an integration is
`rm -rf app/integrations/<name>/` + removing its entry from `OPTIONAL`.

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


## Integration dev notes

Each integration is a vertical slice in `app/integrations/<name>/` (see structure
above). **Feature behaviour, what each panel shows and env setup live in the
README** — below are only the non-obvious implementation gotchas per slice.

### Linky / Conso API (core)
- API `conso.boris.sh/api/consumption_load_curve` (30-min samples, in W). **Max 7 days per request** (8 → 400). `LINKY_TOKEN`/`LINKY_PRM` live in `.env`, **never in code**.
- `compute_daily_hc_hp` (`client.py`) aggregates samples into daily HC/HP kWh **and the talon** = P5 of the day's samples (`_percentile`, `TALON_PCT=5`; P5 not the strict min, which catches the single all-off step). Persisted in `daily_consumption.talon_w` (idempotent `ALTER TABLE` in `init_schema`).
- The load curve returns history, so `fetch_and_cache` forces a **one-time refetch** of cached weeks still missing `talon_w` (the talon backfills; HC/HP, solar and cumulus do not). `build_core._compute_talon` derives yesterday / avg / trend.

### EcoFlow PowerStream / Solar
- The Developer API exposes only instantaneous PV watts; the daily counter (`254_32`) is app-MQTT-only and arrives on a slow, non-forceable timer. So we read the **inverter heartbeat** (protobuf `cmd_func=20 / cmd_id=1` → `PowerStreamInverterHeartbeat`, PV watts = `(pv1 + pv2) / 10` deci-watts) and integrate it into `daily_production` (`_on_solar_power`).
- **Keep-alive**: the device only publishes while polled — re-publish `build_get_quota_request` (cmd 20/1, src=dest=32) to `/app/{userId}/{sn}/thing/property/get` every 60s.
- Auth: `POST /auth/login` (password base64, `scene=IOT_APP`) → token + userId; `GET /iot-auth/app/certification` → MQTT creds (`mqtt-e.ecoflow.com:8883`). **TLS needs `certifi.where()`** or the handshake fails (macOS python.org / Docker slim).

### Crypto Bot panel
- GraphQL `query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode } }`; `% = totalProfitUsdc / sommeMiseUsdc * 100`, portfolio = their sum. Slice `crypto/` (`graphql/`).
- Fetched **on the ESP32 `/display` pull** (re-renders with fresh crypto; Linky/solar stay on the hourly cache); any failure falls back to the cached buffer.
- Thousands separator: plain space — Arial renders U+202F as a tofu box on e-paper.

### Cumulus (water heater)
- The Legrand 412171 contactor exposes `power` (W) but **no kWh counter** → we integrate the reported power into `daily_cumulus` ourselves (`_on_cumulus_power`, same technique as solar). No backfill.
- Z2M broker (mosquitto): subscribe `zigbee2mqtt/cumulus`, read `power`; re-request `{"power":""}` on `.../get` every 60s so integration keeps getting samples during steady heating.

### Bottom table rendering (Cumulus + Talon)
- `renderer._draw_bottom_table`; `_build_bottom_rows` builds the rows (Cumulus if enabled, then Talon, always). 3-column grid: name + yesterday left-aligned at fixed thirds, avg + trend right-aligned; single 1px top separator (no box; not the *space-between* `_draw_stats_bar` of the title banners). `_bottom_table_height` grows with the row count, and the consumption chart shrinks by it.

### Networking
- The dashboard runs in `network_mode: bridge`, so it reaches co-located services (crypto bot, MQTT brokers) via their **LAN IP**, not `localhost`.

### Layout margin
- The whole dashboard is inset by the global `MARGIN` (2px) via `CHART_LEFT`/`CHART_TOP`/`CHART_BOTTOM`; right-anchored banners use `WIDTH - CHART_LEFT`.

