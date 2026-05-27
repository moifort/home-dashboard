#ifndef __CONFIG_H_
#define __CONFIG_H_

// ----- Pin definitions for Seeed XIAO ESP32-S3 -----
#define PIN_BUSY    1   // D0 = GPIO1
#define PIN_RST     2   // D1 = GPIO2
#define PIN_DC      3   // D2 = GPIO3
#define PIN_CS_M    4   // D3 = GPIO4 — master panel chip select
#define PIN_CS_S    5   // D4 = GPIO5 — slave panel chip select
#define PIN_CLK     7   // D8 = GPIO7 — SPI clock (bit-banged)
#define PIN_DIN     9   // D10 = GPIO9 — SPI MOSI (bit-banged)

// ----- Display constants -----
// Physical resolution: 1360x480
// Driver width: 1360/2 = 680 (each byte holds 4 pixels at 2 bits each)
#define DISPLAY_WIDTH       680
#define DISPLAY_HEIGHT      480
#define DISPLAY_BUFFER_SIZE 163200  // (680 / 4) * 480 * 2 panels... actually 680*480/4*2 = 163200

// ----- Network / behavior -----
#define AP_SSID             "Linky-Setup"
#define DEEP_SLEEP_SECONDS  3600
#define WIFI_TIMEOUT_MS     15000
#define WIFI_MAX_RETRIES    3

// ----- NVS namespace -----
#define NVS_NAMESPACE       "linky"

#endif
