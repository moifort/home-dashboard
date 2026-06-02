# Linky e-Paper Dashboard

<p align="center">
  <img src="hardware/device.jpg" alt="Dashboard on its stand" width="760">
</p>

Monitor your electricity consumption from a Linky smart meter on an e-paper display. The dashboard shows the last 9 days of consumption with off-peak/peak breakdown and key indicators to track your savings. Optionally, it also shows **daily solar production** from an EcoFlow PowerStream, a **crypto-bot stats banner**, the **water-heater (cumulus) daily consumption**, a **water meter daily consumption** chart (`Eau`, top-center), and a **UniFi network panel** (internet/Wi-Fi quality, clients and top consumers) in the bottom-right. The empty top-left gutter holds a **`Home`** panel (screen-refresh schedule) and an **`Alertes`** status board that turns the daily trends into plain-language notes per domain, with their financial impact.

Rendered output:

<p align="center">
  <img src="server/scripts/preview.png" alt="Dashboard preview" width="760">
</p>

## Dashboard readings

### Bar chart

Each bar represents one day of electricity consumption. Bars are stacked:

- **Black fill** — peak hours (HP) consumption
- **Top line separator** — marks the boundary between off-peak and peak
- **White section above the line** — off-peak hours (HC) consumption
- **Value above the bar** — total kWh for that day
- **N/A** — incomplete data (less than 1 kWh recorded, typically a meter reporting gap)

### Stats banner

Three indicators are displayed above the chart. Each shows a **current value** and a **trend** compared to the previous 4 weeks.

| Indicator | Value | Trend calculation |
|-----------|-------|-------------------|
| **kWh/j** | Average daily consumption over the last 9 days | `(current_avg - prev_avg) / prev_avg × 100` — ▼ means you're consuming less |
| **HC %** | Ratio of off-peak consumption to total | `current_ratio - prev_ratio` (points) — ▲ means more off-peak usage (good) |
| **€/j** | Average daily cost (HP×price_hp + HC×price_hc + subscription/30.44) | Same % formula as kWh/j — ▼ means you're spending less |

- **▼ in black** = improving (less consumption or cost)
- **▲ in black** = improving (more off-peak ratio)
- **▼ in red** = degrading (less off-peak ratio)
- **▲ in red** = degrading (more consumption or cost)
- Days with less than 1 kWh are excluded from all calculations

### Solar production (optional, top chart)

When an EcoFlow PowerStream is configured, the top half shows daily solar production as full-black bars (last 9 completed days). The stats banner shows the **daily average** (`kWh/j`) with its trend (▲ in black = producing more, good), the **period total** (`Total … kWh`) with the **money saved** over the period (`€`, the total valued at the peak/HP grid price), and the **talon coverage** (`Talon … %`) — the share of the house's baseline-power energy the solar covers, i.e. the average daily production over the talon's daily energy (`avg_w × 24h`). The talon coverage sits to the left of the `Total` group and falls back to `Talon N/A` until the talon is known. See the setup section below.

### Crypto-bot banner (optional, top-right)

When a crypto-bot GraphQL endpoint is configured, an inline title-style banner is drawn in the top-right space (same look as the chart titles): a `Crypto` label, then the **% return** (black when in profit, **red when negative**), `±$profit`, `$portfolio`, and a `SANDBOX` badge. Below it a **grid snapshot chart** shows the bot's price levels (left labels + dashed lines), the 7-day price line and a "now" marker with the live price. Any level the bot **skipped** on its last placement cycle (insufficient funds, half-spacing or max-orders) is flagged with a **yellow ▲** right after its price label — mirroring the iOS grid badges; stale cycles (older than 5 min) are ignored. Data is refreshed each time the ESP32 fetches the display. See the setup section below.

### Talon énergétique (baseline power)

A **table** below the consumption chart (under a thin separator line) shows the house's **talon** — its permanent baseline power draw (fridge, internet box, standby loads). For each day, the talon is the **5th percentile (P5)** of the 30-min Linky load curve (in **W**), which captures the true floor without being skewed by the single step where everything happens to be off at once. Each row has three columns — name and **yesterday's** value left-aligned, and the recent **daily average** with its trend (▲ in red = a rising baseline, i.e. more standby waste) right-aligned. The talon is always shown; when the Cumulus integration is enabled its row is stacked above the Talon row in the same table.

### Cumulus consumption (optional)

When a Zigbee2MQTT broker is configured, a `Cumulus` row is added at the top of the bottom table (above the Talon row), showing the water-heater's daily consumption: yesterday's kWh and the recent daily average with its trend (last 9 days vs the previous 4 weeks; ▲ in red = consuming more). The contactor reports only instantaneous power, so daily kWh are integrated over time (no historical backfill). See the setup section below.

### Water consumption (optional, top-center)

When an MQTT broker is configured, an `Eau` chart is drawn in the top-center space, between the Solar chart and the Crypto panel. It shows the last **9 days** of water use as daily-litres bars (the rightmost bar, labelled `Auj.`, is **today** and grows as the day accumulates), with a title showing the average **L/day** (and its trend), the month-to-date volume in **m³** and its **€** cost. An ESPHome wM-Bus reader publishes the meter's **cumulative index (m³)** to the broker; the dashboard derives daily litres by **index difference** (not power integration, unlike Cumulus), so history starts at the first connection (no backfill). A day with no reading shows **N/A** — including today until its first frame arrives. See the setup section below.

### Home & Alertes (top-left gutter)

The empty space to the left of the packed columns holds two stacked sections.

- **`Home`** — the screen-refresh schedule on one line: the time the image was actually pulled by the panel (`Écran`) and the next refresh, e.g. `14:01 ► 16:00`. The left time is the **real moment of the `GET /display`** (recomputed on every pull); the right time is the next clock-aligned wake boundary. The server regenerates the buffer a few minutes before each wake.
- **`Alertes`** — an always-on **status board**, one section per monitored domain (`EDF`, `Eau`, `Solaire`, `Réseau`, `Cumulus`, `Crypto`). Each domain is a section title; under it, plain-language notes turn the daily trends into something a human reads at a glance. A **problem** is written entirely in **red** (e.g. *Forte hausse de consommation 15%/j*, *Fuite d'eau probable 240 L*, *Panneaux solaires déconnectés ?*, *Latence réseau élevée 78 ms*), a **positive** note entirely in **black** (e.g. *Forte production solaire 45%*, *Belle baisse de consommation*, *Bot devant le hold +5%*). When computable, each line ends with its **financial impact** — `dépense`/`économie` in €/j (EDF consumption, off-peak shift, standby, cumulus, water), € for solar (production value) or `gain`/`manque` in $ for **Crypto** (the strategy's edge over buy-and-hold, estimated from the **alpha** × the invested amount). A domain with nothing wrong shows *Rien à signaler*. Because vertical space is limited, the domains with the **most alerts** are listed first (then by severity), and the quiet ones last. Detection is purely **trend-based** from the values already computed by each integration — no extra capture; thresholds are hard-coded constants in `app/alerts.py` and reuse `PRICE_HP`/`PRICE_HC`.

### UniFi network panel (optional, bottom-right)

When a UniFi gateway (UniFi OS) is configured, a `Réseau` panel is drawn in the bottom-right, under the crypto grid. The title shows the **internet quality** (ISP name + health %, the share of WAN samples without downtime) and the **Wi-Fi quality** (per-standard satisfaction, weighted by the number of connected stations), each with a ▲▼ trend. Below it: **latency** (average WAN latency over the window), **Wi-Fi signal** (average client experience score) and **data usage** (yesterday / the rolling 30 complete days ending yesterday, from the daily WAN report — a full window that stays comparable day-to-day, unlike a calendar month that resets on the 1st). Then a **top-4 clients** mini-table per network — the main Wi-Fi first, then the IoT Wi-Fi, each header showing its actual SSID name (from `UNIFI_SSID_MAIN`/`UNIFI_SSID_IOT`) — tagged "· aujourd'hui" (the traffic is each client's current-session rx+tx) with its client count, ranked by their rx+tx traffic. Trends compare the latest day to a 7-day average from a daily snapshot (no backfill — they fill in over the first week); a latency rise reads as a degradation (red) and data usage stays neutral (black). See the setup section below.

## Hardware

| Component | Reference |
|-----------|-----------|
| e-Paper display | [Waveshare 10.85" (G) 4-color](https://www.waveshare.com/10.85inch-e-paper-hat-plus.htm) |
| Microcontroller | [Seeed XIAO ESP32-S3](https://www.seeedstudio.com/XIAO-ESP32S3-p-5627.html) |
| Server | Any Docker host (CasaOS, Raspberry Pi, NAS...) |
| 3D printed case | [Dashboard.3mf](hardware/case/Dashboard.3mf) — matte PLA recommended |

## Installation

### 1. Get a Linky token

1. Go to [conso.boris.sh](https://conso.boris.sh)
2. Log in with your Enedis account
3. Authorize data access
4. Copy the JWT token (valid for 3 years)

### 2. Configure environment variables

```bash
cp server/infra/.env.example server/infra/.env
```

Edit `server/infra/.env` with your values:

```env
# Required — your Linky token
LINKY_TOKEN=eyJhbGci...your_token

# Your meter PRM (14 digits, visible on your meter or on Enedis)
LINKY_PRM=your_prm_here

# Off-peak hours windows (format: HH:MM-HH:MM, comma-separated)
# Check your electricity contract for your specific time slots
HC_WINDOWS=23:32-5:32,15:02-17:02

# Your contract pricing (€/kWh)
PRICE_HP=0.2065
PRICE_HC=0.1579
PRICE_ABO_MONTHLY=15.65

# Screen-refresh schedule. The ESP32 wakes every SCREEN_REFRESH_INTERVAL_MIN
# minutes (clock-aligned) — must match REFRESH_INTERVAL_MIN in the firmware.
# The server regenerates the buffer DATA_LEAD_MIN minutes before each wake.
SCREEN_REFRESH_INTERVAL_MIN=120
DATA_LEAD_MIN=10
```

#### Optional — EcoFlow PowerStream solar production

Add your EcoFlow account credentials to display daily solar production above the consumption chart. The server connects to EcoFlow's app MQTT broker, reads the inverter's reported PV power, and integrates it into daily kWh totals (the official Developer API only exposes instantaneous watts, with no historical counter). The chart shows the **last 9 completed days** — today is excluded (a partial day is not a reliable total), and days without data show as **N/A**. There is **no backfill**: the history starts at the first connection and fills in day by day.

```env
ECOFLOW_EMAIL=your_ecoflow_account_email
ECOFLOW_PASSWORD=your_ecoflow_account_password
ECOFLOW_DEVICE_SN=your_powerstream_serial_number
ECOFLOW_API_HOST=api-e.ecoflow.com   # EU; use api.ecoflow.com (global) or api-a.ecoflow.com (asia)
```

#### Optional — Crypto-bot stats panel

Point the dashboard at your crypto-bot's GraphQL endpoint to show its trading stats in the top-right corner. Because the dashboard container uses a bridge network, use the bot's **LAN IP** (not `localhost`) when both run on the same host. The panel is fetched whenever the ESP32 pulls the display and is omitted if the endpoint is unreachable.

```env
CRYPTO_API_URL=http://192.168.1.50:3003/graphql
CRYPTO_API_TOKEN=your_crypto_bot_api_token   # the bot's NITRO_API_TOKEN; omit if no auth
```

#### Optional — Cumulus (water-heater) consumption

Point the dashboard at your Zigbee2MQTT broker to show the water-heater's daily consumption. The `cumulus` device (a Legrand contactor) reports only instantaneous power, so the server subscribes to its MQTT topic and integrates that power into daily kWh — there is **no backfill**, the history starts at the first connection. Use the broker's **LAN IP** (bridge network). Credentials are optional if the broker allows anonymous connections.

```env
CUMULUS_MQTT_HOST=192.168.1.50
CUMULUS_MQTT_PORT=1883
CUMULUS_TOPIC=zigbee2mqtt/cumulus
CUMULUS_MQTT_USERNAME=                 # omit if the broker is anonymous
CUMULUS_MQTT_PASSWORD=
```

#### Optional — UniFi network panel

Point the dashboard at your local UniFi gateway (UCG/UDM running UniFi OS) to show a `Réseau` panel with internet & Wi-Fi quality, per-SSID client counts and the top consumers. It logs in with your **local** gateway account (cookie auth; the self-signed certificate is trusted automatically) and reads the aggregated dashboard + active clients. Use the gateway's **LAN IP** (bridge network). Set `UNIFI_SSID_IOT`/`UNIFI_SSID_MAIN` to your own SSID names so the IoT vs personal split is correct. Trends build up over the first week (no backfill). Enabled by setting `UNIFI_PASSWORD`.

```env
UNIFI_HOST=https://192.168.1.1
UNIFI_USERNAME=your_gateway_local_account
UNIFI_PASSWORD=your_gateway_password
UNIFI_SITE=default
UNIFI_SSID_IOT=your_iot_wifi_ssid      # your IoT Wi-Fi SSID
UNIFI_SSID_MAIN=your_main_wifi_ssid    # your main Wi-Fi SSID
```

#### Optional — Water meter consumption

Point the dashboard at the MQTT broker where an ESPHome wM-Bus reader publishes your water meter's **cumulative index (m³)**. The dashboard derives daily litres by **index difference** (not power integration, unlike Cumulus) — there is **no backfill**, the history starts at the first connection. Use the broker's **LAN IP** (bridge network). Credentials are optional if the broker allows anonymous connections. Set `WATER_PRICE_M3` (water + sanitation, €/m³) to show the monthly cost.

```env
WATER_MQTT_HOST=192.168.1.50
WATER_MQTT_PORT=1883
WATER_TOPIC=watermeter/index_m3        # cumulative index in m³ (raw float payload)
WATER_MQTT_USERNAME=                   # omit if the broker is anonymous
WATER_MQTT_PASSWORD=
WATER_PRICE_M3=4.30                    # €/m³ for the cost figure (0 = hide cost)
```

### 3. Run with Docker Compose

```bash
curl -O https://raw.githubusercontent.com/moifort/dashboard/main/server/infra/docker-compose.yml
docker compose up -d
```

The dashboard will be available at `http://your-server:5000`.

### 4. Run on CasaOS

Import the CasaOS compose file from the CasaOS interface using this URL:

```
https://raw.githubusercontent.com/moifort/dashboard/main/server/infra/docker-compose.casaos.yml
```

### 5. Flash the ESP32

Requires [Arduino CLI](https://arduino.github.io/arduino-cli/) with `esp32:esp32` core:

```bash
brew install arduino-cli
arduino-cli core install esp32:esp32
```

Compile and flash:

```bash
arduino-cli compile --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" hardware/esp32-display/
arduino-cli upload --fqbn "esp32:esp32:XIAO_ESP32S3:PSRAM=opi" --port /dev/cu.usbmodem101 hardware/esp32-display/
```

### 6. Configure the ESP32

On first boot, open the serial monitor:

```bash
arduino-cli monitor --port /dev/cu.usbmodem101 --config baudrate=115200
```

The ESP32 will prompt for:
- **WiFi SSID** and **password**
- **Server URL** (default: `http://192.168.1.50:5000`)

To reconfigure later, type `reset` within 3 seconds of boot.

### Refresh schedule

The ESP32 wakes on a clock-aligned interval (`REFRESH_INTERVAL_MIN`, default **120 min** → 00:00, 02:00 … 22:00 CET/CEST), refreshes the display, then returns to deep sleep until the next boundary. Time is synced via NTP on each wake cycle. On a failed cycle (Wi-Fi, fetch or PSRAM allocation) it deep-sleeps and retries — quick 5-min retries for a brief outage, then backing off to the full interval to save battery — so it always returns to sleep.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/display` | EPD binary buffer (163,200 bytes) — for the ESP32 |
| `GET` | `/` | HTML preview of the dashboard in a browser |
| `GET` | `/status` | Server status as JSON (last fetch, cache, config) |
| `POST` | `/refresh` | Force a data refresh |

## Development / tests

A golden-master test suite guards the render pipeline against regressions. It
freezes a known input (a seeded SQLite DB + a fixed clock) and compares the
output byte-for-byte to committed references:

- **Data pipeline** — `build_dashboard_data()` → `server/tests/fixtures/data.golden.json`
  (portable; covers the orchestrator, the DB-backed slices and the alerts engine).
- **Render** — `render_dashboard()` → `png_to_epd_buffer()` →
  `server/tests/fixtures/display.golden.bin` (the 163,200-byte EPD buffer).

```bash
cd server
pip install -r requirements-dev.txt
pytest -q                 # must stay green: nothing changed
pytest -q --update-golden # re-baseline after an intentional layout/data change
```

On a render mismatch the actual/golden/diff PNGs are written to `/tmp`. CI runs
the suite on every push and pull request (`.github/workflows/tests.yml`).

The render golden is sensitive to the FreeType/Pillow build (`Pillow` is pinned),
which differs across platforms by ~5% of the buffer for the same layout. So the
committed render golden is generated **locally** and the render check is strict
(`GOLDEN_TOLERANCE=0`, byte-exact) on that machine, while **CI runs it as a smoke
test** (`GOLDEN_TOLERANCE=0.10`, catching only gross breakage). The **data**
golden is byte-exact everywhere and is the precise cross-platform gate.

## 3D Printed Case

The [Dashboard.3mf](hardware/case/Dashboard.3mf) file contains the printable case. Recommended settings:

- **Material**: matte PLA (cleaner look, no reflections)
- **Infill**: 15%
- **Supports**: none

## License

MIT
