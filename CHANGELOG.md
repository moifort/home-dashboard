# Changelog

## 2026-05-28

- **Crypto-bot stats banner** — optional inline title-style banner in the top-right (same look as the chart titles): a `Crypto` label, the bot's % return (red when negative), signed profit, portfolio value and a `SANDBOX` badge. Fetched over GraphQL when the ESP32 pulls `/display`, with graceful fallback to the cached buffer. Enabled by setting `CRYPTO_API_URL` (and optionally `CRYPTO_API_TOKEN`).

- **EcoFlow PowerStream solar production** — optional daily solar production chart in the top half of the screen (full-black bars), above the consumption chart. Reads the inverter's reported PV power over the EcoFlow app MQTT broker (kept alive by a periodic get-quota request) and integrates it into daily kWh totals; shows the last 9 completed days (N/A until data accumulates), daily average and trend. History starts at first connection (no backfill). Enabled by setting `ECOFLOW_EMAIL`/`ECOFLOW_PASSWORD`/`ECOFLOW_DEVICE_SN`.
- **Bundled Arial font** — the renderer now ships Arial in the repo and uses it everywhere, so Docker output is pixel-identical to local renders (previously Docker fell back to Liberation Sans, which looked less sharp at small sizes)

## 2026-05-27

- **ESP32 serial configuration** — WiFi and server URL configured via serial monitor instead of captive portal
- **NTP-based refresh schedule** — display updates at 8:00 and 17:00 (CET/CEST) instead of every hour
- **Pillow bitmap renderer** — pixel-perfect text rendering using FreeType with `fontmode='1'`, replacing Playwright/Chromium
- **N/A days handling** — days with less than 1 kWh are shown as "N/A" and excluded from stats
- **Stats filtering** — trend calculations ignore incomplete data days
