# Changelog

## 2026-05-30

- **UniFi network panel** — optional `Réseau` panel in the bottom-right (under the crypto grid): internet (ISP uptime %) and Wi-Fi quality in the title, then latency, Wi-Fi signal score, speed test (↓/↑), data usage (yesterday/month), and the top-3 clients per SSID with per-network client counts (main Wi-Fi first, then IoT). ▲▼ trends (7-day average from a `daily_unifi` snapshot, no backfill) on internet/Wi-Fi, latency, speed (up = good) and data usage (neutral, black). Talks to the local UniFi gateway (cookie auth, self-signed cert). Enabled by setting `UNIFI_PASSWORD`.
- **Crypto grid warning markers** — the grid snapshot now flags the bot's last placement cycle: a full-yellow ▲ is drawn right after the Y-axis price label of every skipped level (insufficient funds, half-spacing or max-orders), mirroring the iOS grid badges. Only the marked level's dashed line is shortened to make room — the other lines keep their full width — and markers from a cycle older than 5 minutes are dropped.
- **Solar talon coverage** — the solar title now ends with a `Talon … %` item: the share of the house's baseline-power (talon) energy the solar production covers, computed from the 9-day averages (average daily PV kWh over the talon's daily energy, `avg_w × 24h`). Always shown — falls back to `Talon N/A` until the talon is known — and positioned to the left of the `Total … kWh` group (then the `€`).
- **Talon énergétique** — the dashboard now computes the house's baseline power (the P5 of each day's 30-min Linky load curve, in W — the permanent floor: fridge, box, standby), persisted in `daily_consumption.talon_w` and backfilled from the load-curve history.
- **Bottom table (Cumulus + Talon)** — the bottom strip became a 3-column table (name · yesterday · average + trend) under a single top separator line: the name and yesterday columns are left-aligned, the average+trend column is right-aligned. The Talon row is always shown (core Linky data), with the Cumulus row stacked above it when that integration is enabled.
- **2px screen margin** — the whole dashboard is now inset 2px from every e-paper edge instead of bleeding edge-to-edge.
- **Internal refactor (no behavior change)** — the loose root modules became an `app/`
  package organized as vertical slices: each integration (`linky`, `ecoflow`, `cumulus`,
  `crypto`) is a self-contained folder owning its config, storage, transport (in tech
  subfolders `mqtt/`/`proto/`/`graphql/`/`api/`), integrator and render panel, wired
  through an `OPTIONAL` registry. Dead code removed (`templates/`, `send_to_esp32`). The
  server now runs with `python -m app`. Fonts co-located under `app/rendering/fonts/`,
  `Dashboard.3mf` moved to `hardware/`, and the local runtime dir is now `.data/`.

- **Crypto profit grouping** — the Crypto banner now groups the bot's results behind a `Profits` label: the signed `%` return and the `±$` amount on one line (red when negative), keeping the portfolio value as a separate segment.
- **Crypto alpha** — the Crypto banner now shows an `α` segment: the bot's excess return over buy-and-hold (all-time bot return minus `holdReturnPercent`), black when ahead, red when behind.
- **Crypto grid snapshot chart** — under the Crypto banner (top-right): the grid price levels with left labels and dashed lines, the 7-day price line, and a "now" marker dot with the live current price. Rendered black & white. Reuses the existing `CRYPTO_API_URL`/`CRYPTO_API_TOKEN` (fetched live on the ESP32's `/display` pull).
- **`scripts/gen_preview.py`** — regenerates `docs/preview.png` from the local DB history + live crypto, for UI review.
- **Cumulus banner** — now shows **yesterday's** completed daily consumption (`kWh hier`) instead of today's partial total, and moves to a full-width row at the very **bottom of the screen, below the EDF chart** (which shrinks slightly to make room).
- **Chart split** — the solar chart is slightly shorter so the EDF chart gets a bit more height.

## 2026-05-29

- **Chart title labels** — the solar and consumption titles now lead with a `Solaire`/`EDF` label (matching the `Crypto`/`Cumulus` banners), with tighter spacing between each value and its trend.
- **Solar money saved** — the EcoFlow title now shows the euros saved over the period (production total valued at the peak/HP grid price), next to the `kWh total`.
- **Cumulus consumption trend** — the water-heater banner now shows a trend on its daily average (last 9 days vs the previous 4 weeks; ▲ in red = consuming more).
- **Edge-to-edge layout** — removed the screen margins on all four sides so the charts and banners fill the full display; the spacing between the two stacked charts is preserved.

## 2026-05-28

- **Cumulus (water-heater) consumption** — optional inline title-style banner (top-right, under the crypto one) showing the water-heater's daily kWh and recent daily average. The Zigbee contactor (Legrand 412171) reports only instantaneous power, so daily kWh are integrated over time from its Zigbee2MQTT power topic (no historical backfill). Enabled by setting `CUMULUS_MQTT_HOST`.
- **Crypto-bot stats banner** — optional inline title-style banner in the top-right (same look as the chart titles): a `Crypto` label, the bot's % return (red when negative), signed profit, portfolio value and a `SANDBOX` badge. Fetched over GraphQL when the ESP32 pulls `/display`, with graceful fallback to the cached buffer. Enabled by setting `CRYPTO_API_URL` (and optionally `CRYPTO_API_TOKEN`).

- **EcoFlow PowerStream solar production** — optional daily solar production chart in the top half of the screen (full-black bars), above the consumption chart. Reads the inverter's reported PV power over the EcoFlow app MQTT broker (kept alive by a periodic get-quota request) and integrates it into daily kWh totals; shows the last 9 completed days (N/A until data accumulates), daily average and trend. History starts at first connection (no backfill). Enabled by setting `ECOFLOW_EMAIL`/`ECOFLOW_PASSWORD`/`ECOFLOW_DEVICE_SN`.
- **Bundled Arial font** — the renderer now ships Arial in the repo and uses it everywhere, so Docker output is pixel-identical to local renders (previously Docker fell back to Liberation Sans, which looked less sharp at small sizes)

## 2026-05-27

- **ESP32 serial configuration** — WiFi and server URL configured via serial monitor instead of captive portal
- **NTP-based refresh schedule** — display updates at 8:00 and 17:00 (CET/CEST) instead of every hour
- **Pillow bitmap renderer** — pixel-perfect text rendering using FreeType with `fontmode='1'`, replacing Playwright/Chromium
- **N/A days handling** — days with less than 1 kWh are shown as "N/A" and excluded from stats
- **Stats filtering** — trend calculations ignore incomplete data days
