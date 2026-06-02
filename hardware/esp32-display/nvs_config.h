#ifndef __NVS_CONFIG_H_
#define __NVS_CONFIG_H_

#include <Arduino.h>

#define NVS_NAMESPACE       "linky"
#define DEFAULT_SERVER_URL  "http://192.168.1.50:5000"
#define DISPLAY_BUFFER_SIZE 163200
#define RETRY_SLEEP_US      300000000ULL
#define MAX_QUICK_RETRIES   3
#define REFRESH_INTERVAL_MIN 120
#define WIFI_TIMEOUT_MS     15000
#define WIFI_MAX_RETRIES    3
#define BOOT_WAIT_MS        3000

bool loadConfig(String &ssid, String &pass, String &serverUrl);
void saveConfig(const String &ssid, const String &pass, const String &serverUrl);
void clearConfig();

#endif
