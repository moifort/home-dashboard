# Linky e-Paper Dashboard

Monitor your electricity consumption from a Linky smart meter on an e-paper display. The dashboard shows the last 9 days of consumption with off-peak/peak breakdown and key indicators to track your savings.

![Dashboard preview](docs/preview.png)

## What it does

- **Daily consumption** — stacked bar chart with off-peak (HC) and peak (HP) breakdown for each day
- **Average kWh/day** — with progression compared to the previous 4 weeks
- **Off-peak ratio** — to verify you're shifting consumption to off-peak hours
- **Average cost per day** — to track savings in euros
- **Red progressions** — when things go the wrong way (consuming more, spending more)
- **Automatic refresh** — the server updates data every hour

## Hardware

| Component | Reference |
|-----------|-----------|
| e-Paper display | [Waveshare 10.85" (G) 4-color](https://www.waveshare.com/10.85inch-e-paper-hat-plus.htm) |
| Microcontroller | [Seeed XIAO ESP32-S3](https://www.seeedstudio.com/XIAO-ESP32S3-p-5627.html) |
| Server | Any Docker host (CasaOS, Raspberry Pi, NAS...) |
| 3D printed case | [Dashboard.3mf](Dashboard.3mf) — matte PLA recommended |

## Installation

### 1. Get a Linky token

1. Go to [conso.boris.sh](https://conso.boris.sh)
2. Log in with your Enedis account
3. Authorize data access
4. Copy the JWT token (valid for 3 years)

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

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

# Refresh interval in seconds (default: 1 hour)
REFRESH_INTERVAL=3600
```

### 3. Run with Docker Compose

```bash
curl -O https://raw.githubusercontent.com/moifort/dashboard/main/docker-compose.yml
docker compose up -d
```

The dashboard will be available at `http://your-server:5000`.

### 4. Run on CasaOS

Import the CasaOS compose file from the CasaOS interface using this URL:

```
https://raw.githubusercontent.com/moifort/dashboard/main/docker-compose.casaos.yml
```

Or manually:

```bash
curl -O https://raw.githubusercontent.com/moifort/dashboard/main/docker-compose.casaos.yml
docker compose -f docker-compose.casaos.yml up -d
```

### 5. Flash the ESP32

Flash the firmware from `../esp32-display/` to your XIAO ESP32-S3 using PlatformIO. The ESP32 must be on the same WiFi network as your server.

### 6. Connect the ESP32 to the server

The ESP32 must call `GET http://your-server:5000/display` to retrieve the image to display. The endpoint returns the raw binary buffer of 163,200 bytes.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/display` | EPD binary buffer (163,200 bytes) — for the ESP32 |
| `GET` | `/` | HTML preview of the dashboard in a browser |
| `GET` | `/status` | Server status as JSON (last fetch, cache, config) |
| `POST` | `/refresh` | Force a data refresh |

## 3D Printed Case

The [Dashboard.3mf](Dashboard.3mf) file contains the printable case. Recommended settings:

- **Material**: matte PLA (cleaner look, no reflections)
- **Infill**: 15%
- **Supports**: none

## License

MIT
