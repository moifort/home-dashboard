# Dashboard e-Paper — Development Guide

## Architecture

The repo is split in two top-level sides; the root itself stays minimal (README,
CHANGELOG, CLAUDE.md + hidden config):

```
hardware/                # everything physical
  esp32-display/         # Arduino firmware (sketch name == folder name)
  case/Dashboard.3mf     # 3D-printed enclosure
  device.jpg             # device photo (README)
server/                  # the server side — the Python import ROOT
  requirements.txt  requirements-dev.txt
  infra/                 # Dockerfile + docker-compose*.yml + .env.example
  tests/                 # golden-master net (run pytest from server/)
  scripts/               # gen_preview.py (+ committed preview.png)
  app/                   # the Python package (run `python -m app` from server/)
```

**Run everything from `server/`** (`cd server` → `python -m app`, `pytest`): `app`
and `tests` are top-level packages whose import root is `server/`.

- **`app/` package** (`server/app/`): Python Docker server (CasaOS, port 5000, run with `python -m app`) that fetches Linky data, renders the dashboard bitmap with **Pillow** (`app/rendering/renderer.py` → `ImageDraw`, no browser), converts it to the 4-color EPD buffer (`app/rendering/converter.py`), and serves it at `/display` for the ESP32 to pull

### app/ package structure (vertical slices)
```
server/app/
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
    power/   {mqtt/, __init__.py}                  # config-driven MQTT power sensors
    crypto/  {graphql/, __init__.py}
```
Each integration's `__init__.py` exposes the uniform slice API — `enabled()`,
`init_schema()`, `start()`, `attach(data)`, `status()` — and owns its env config,
DB table, power integrator and render panel. Tech-specific transport lives in a
subfolder (`mqtt/`, `proto/`, `graphql/`, `api/`). Removing an integration is
`rm -rf server/app/integrations/<name>/` + removing its entry from `OPTIONAL`.

## Tests / Anti-regression (golden master) — READ BEFORE ANY REFACTOR

A golden-master net (`server/tests/`) guards the pipeline against regressions.
**Run pytest from `server/`.** **Factor it into any refactor plan**: it freezes a
known input and compares the output bit-for-bit against a committed reference.

- **Layer 1** `server/tests/test_data_pipeline.py`: seeded DB + frozen clock →
  `build_dashboard_data()` → `server/tests/fixtures/data.golden.json`. Covers the
  orchestrator, the DB-backed slices (linky core, solar, cumulus, water) and the
  alerts. **Portable** (byte-exact on macOS/Linux, no font rendering).
- **Layer 2** `server/tests/test_render_golden.py`: full frozen dict →
  `render_dashboard()` → `png_to_epd_buffer()` → `server/tests/fixtures/display.golden.bin`
  (163,200 bytes). Sensitive to FreeType/Pillow (**`Pillow` pinned**); tolerance
  `GOLDEN_TOLERANCE` (default 0); actual/golden/diff PNGs written to `/tmp` on a mismatch.

Workflow (from `server/`):
- **Before/during a refactor**: `pytest -q` must stay **green** (nothing changed
  visibly). `pip install -r requirements-dev.txt` if pytest is missing.
- **Intentional** layout/data change: `pytest --update-golden`, inspect the diff
  (`/tmp/render_diff.png`), re-commit the goldens **in the same commit**.
- Details: deterministic DB and `FIXED_NOW=2026-06-02` in `server/tests/fixtures/seed_db.py`.
- **Per-platform guard**: layer 1 (data, no font rendering) is **byte-exact
  everywhere** → strict guard locally **and** in CI. Layer 2 (rendering) depends on
  **FreeType**, which differs macOS↔Linux by about **5%** of the buffer for an
  identical layout → the golden (generated on the Mac) can't be byte-exact in CI.
  So: **strict on the local Mac** (tolerance 0, that's where you judge the
  rendering), **smoke test in CI** (`GOLDEN_TOLERANCE=0.10` in
  `.github/workflows/tests.yml`, only catches gross breakage). The committed
  rendered golden is **the Mac's** — regenerate it locally (`--update-golden`), not
  in CI.

## e-Paper Display

- **Model**: Waveshare 10.85" **(G) 4-color** (black, white, yellow, red)
- **Driver**: `epd10in85g` — NEVER `epd10in85` (B/W), different init sequence
- **Resolution**: 1360×480, 2 bits/pixel, buffer = 163,200 bytes
- **ESP32 IP**: variable (scan with `arp -a | grep esp32`)

## ESP32 Firmware (hardware/esp32-display/)

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
arduino-cli compile --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" hardware/esp32-display/

# Flash (port may vary — check with: ls /dev/cu.usb*)
arduino-cli upload --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" --port /dev/cu.usbmodem101 hardware/esp32-display/

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
- **After any UI change, regenerate `server/scripts/preview.png` and open it in the macOS Preview app** (`open -a Preview server/scripts/preview.png`) so the user can review the result

## Documentation language

- **Docs are fully English.** All Markdown (`README.md`, `CHANGELOG.md`,
  `CLAUDE.md`) reads in English so any developer understands it — prose,
  headings, examples. When you reference a string the screen shows in French,
  keep the literal (so the doc still matches the device) **and add an English
  gloss**: e.g. the `Réseau` (Network) panel, the `Eau` (Water) chart, an alert
  like *Forte hausse de consommation* (sharp rise in consumption), the
  `aujourd'hui` (today) tag. Never leave a French word a reader would need French
  to understand — that's why it's "Talon (baseline power)", not "talon
  énergétique".
- **Code keeps its French UI labels — never translate them.** The dashboard
  renders in French; the on-screen strings in the code (renderer labels, panel
  titles, alert messages) must stay French. Only the docs that *describe* them
  are in English. Code identifiers, paths and env-var names stay verbatim.

## Git Workflow

- **Never `git push` automatically** — push only when the user says "push"
- On push: review local commits (`git log --oneline origin/main..HEAD`), squash reverts/serial fixes, clean up history
- Suggest pushing when good progress is made or a milestone is reached
- Commit after each verified change, but push is a deliberate act

### Pre-push docs & quality checklist (run EVERY push)

Before pushing, verify and update as needed:
- **CHANGELOG.md** — an entry exists for every user-facing change in the push.
- **README.md** — features, readings, endpoints and the **Optional** env setup blocks are complete and accurate (every new integration documented).
- **`server/infra/docker-compose.yml` + `server/infra/docker-compose.casaos.yml`** — every new env var is declared (empty default = disabled), ports/volumes correct, image/labels valid.
- **`server/infra/.env.example`** — every new env var present with a helpful comment.
- **`server/scripts/preview.png`** — regenerated when the rendered layout changed.
- **Environment variables** — if the push adds/renames env vars, tell the user which ones to add or fill on their CasaOS deployment.


## Integration dev notes

Each integration is a vertical slice in `server/app/integrations/<name>/` (see structure
above). **Feature behaviour, what each panel shows and env setup live in the
README** — below are only the non-obvious implementation gotchas per slice.

### Linky / Conso API (core)
- API `conso.boris.sh/api/consumption_load_curve` (30-min samples, in W). **Max 7 days per request** (8 → 400). `LINKY_TOKEN`/`LINKY_PRM` live in `.env`, **never in code**.
- `compute_daily_hc_hp` (`client.py`) aggregates samples into daily HC/HP kWh **and the talon** = P20 of the day's **night** samples (`23h–05h`, `TALON_NIGHT_START/END`; `_percentile`, `TALON_PCT=20`). The Conso curve is grid draw, **net of self-consumed solar**, so daytime PV injection would crush the percentile — the night window is solar-free. Over the ~12 night samples P20 ≈ the 3rd lowest, skipping the deepest dips (fridge + all off); a day with no night sample yields `talon_w=None`. Persisted in `daily_consumption.talon_w` (idempotent `ALTER TABLE` + a `PRAGMA user_version=1` migration that NULLs the old 24h talons once so they re-backfill night-only, both in `init_schema`).
- The load curve returns history, so `fetch_and_cache` forces a **one-time refetch** of cached weeks still missing `talon_w` (the talon backfills; HC/HP, solar and cumulus do not). `build_core._compute_talon` derives yesterday / avg / trend.

### EcoFlow PowerStream / Solar
- The Developer API exposes only instantaneous PV watts; the daily counter (`254_32`) is app-MQTT-only and arrives on a slow, non-forceable timer. So we read the **inverter heartbeat** (protobuf `cmd_func=20 / cmd_id=1` → `PowerStreamInverterHeartbeat`, PV watts = `(pv1 + pv2) / 10` deci-watts) and integrate it into `daily_production` (`_on_solar_power`).
- **Keep-alive**: the device only publishes while polled — re-publish `build_get_quota_request` (cmd 20/1, src=dest=32) to `/app/{userId}/{sn}/thing/property/get` every 60s.
- Auth: `POST /auth/login` (password base64, `scene=IOT_APP`) → token + userId; `GET /iot-auth/app/certification` → MQTT creds (`mqtt-e.ecoflow.com:8883`). **TLS needs `certifi.where()`** or the handshake fails (macOS python.org / Docker slim).

### Crypto Bot panel
- GraphQL `query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode } }`; `% = totalProfitUsdc / sommeMiseUsdc * 100`, portfolio = their sum. Slice `crypto/` (`graphql/`).
- Fetched **on the ESP32 `/display` pull** (re-renders with fresh crypto; Linky/solar stay on the hourly cache); any failure falls back to the cached buffer.
- Thousands separator: plain space — Arial renders U+202F as a tofu box on e-paper.

### Power sensors (config-driven, multi-device)
- One generic slice (`integrations/power/`) for **any** Z2M/ESPHome device that reports only instantaneous `power` (W) and no kWh counter — e.g. a `Cumulus` water-heater contactor, a `Lave-linge` plug. Declared in **one env var** `POWER_SENSORS = "topic:Display Name;topic2:Name 2"` (`;`-separated; first `:` splits topic/label). `_parse_sensors` → `Sensor(slug, topic, name)`.
- **Grouping**: topics sharing a `name` are summed into one row. A lone name keeps `slug = _slugify(name)` (backward compatible, history preserved, **no migration**); members of a multi-topic group get `slug = _slugify(name)-_slugify(topic)` so they never collide. `_groups(SENSORS)` returns ordered `(name, [slug…])`; `attach` sums each group's per-topic daily series (`_merged_by_date`, a day reported by ≥1 member shows the sum of present members). The row is the sum of all current members, so which member owns which slug is irrelevant to the total.
- Each topic gets its own `PowerMqttListener` (subscribe its topic, re-request `{"power":""}` on `.../get` every 60s) and its own integrator state keyed by slug (`_make_on_power(slug)`, same technique as solar) — no shared state, no lock. All share one table `daily_power(slug, date, cons_wh, …)` via `db.get_cached_power`/`upsert_power`. No backfill.
- **Legacy migration**: `init_schema()` one-time copies `daily_cumulus`/`daily_washer` into `daily_power` under slugs `cumulus`/`lave-linge` (idempotent; guarded on table-exists + slug-empty). History re-attaches only if the labels stay `Cumulus`/`Lave-linge`.
- Alerts: the `Cumulus` domain + `cumulus_rise/drop` rules look up the sensor **named** `Cumulus` in `data["power_sensors"]` (`alerts._power_sensor`).

### Bottom table rendering (power sensors + Talon)
- `renderer._draw_bottom_table`; `_build_bottom_rows` iterates `data["power_sensors"]` (one row each, in config order), then Talon (always). 3-column grid: name + yesterday left-aligned at fixed thirds, avg + trend right-aligned; single 1px top separator (no box; not the *space-between* `_draw_stats_bar` of the title banners). `_bottom_table_height` grows with the row count, and the consumption chart shrinks by it.

### Networking
- The dashboard runs in `network_mode: bridge`, so it reaches co-located services (crypto bot, MQTT brokers) via their **LAN IP**, not `localhost`.

### Layout margin
- The whole dashboard is inset by the global `MARGIN` (2px) via `CHART_LEFT`/`CHART_TOP`/`CHART_BOTTOM`; right-anchored banners use `WIDTH - CHART_LEFT`.

