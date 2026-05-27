#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

#include "nvs_config.h"
#include "DEV_Config.h"
#include "EPD_10in85g.h"

static String serialReadLine() {
    String line = "";
    while (true) {
        if (Serial.available()) {
            char c = Serial.read();
            if (c == '\n' || c == '\r') {
                if (line.length() > 0) {
                    Serial.println();
                    return line;
                }
            } else {
                line += c;
                Serial.print(c);
            }
        }
        delay(10);
    }
}

static bool checkResetCommand() {
    Serial.println("Type 'reset' within 3s to reconfigure...");
    unsigned long start = millis();
    String input = "";
    while (millis() - start < BOOT_WAIT_MS) {
        if (Serial.available()) {
            char c = Serial.read();
            if (c == '\n' || c == '\r') {
                input.trim();
                if (input.equalsIgnoreCase("reset")) return true;
                input = "";
            } else {
                input += c;
            }
        }
        delay(10);
    }
    return false;
}

static String buildDisplayUrl(const String &serverUrl) {
    String url = serverUrl;
    if (url.endsWith("/")) url += "display";
    else if (!url.endsWith("/display")) url += "/display";
    return url;
}

static bool fetchDisplayBuffer(const String &serverUrl, uint8_t *buf) {
    HTTPClient http;
    String url = buildDisplayUrl(serverUrl);
    Serial.printf("Fetching: %s\n", url.c_str());

    http.begin(url);
    http.setTimeout(30000);

    int httpCode = http.GET();
    if (httpCode != 200) {
        Serial.printf("HTTP error: %d\n", httpCode);
        http.end();
        return false;
    }

    WiFiClient *stream = http.getStreamPtr();
    uint32_t bytesRead = 0;

    while (bytesRead < DISPLAY_BUFFER_SIZE && http.connected()) {
        size_t available = stream->available();
        if (available > 0) {
            size_t toRead = min((size_t)(DISPLAY_BUFFER_SIZE - bytesRead), available);
            size_t got = stream->readBytes(buf + bytesRead, toRead);
            bytesRead += got;
        } else {
            delay(10);
        }
    }

    http.end();
    Serial.printf("Received %lu / %lu bytes\n", (unsigned long)bytesRead, (unsigned long)DISPLAY_BUFFER_SIZE);

    return bytesRead == DISPLAY_BUFFER_SIZE;
}

static bool syncNtp() {
    configTzTime("CET-1CEST,M3.5.0,M10.5.0/3", "pool.ntp.org");
    Serial.print("NTP sync");
    for (int i = 0; i < 20; i++) {
        delay(500);
        Serial.print(".");
        struct tm t;
        if (getLocalTime(&t, 0)) {
            Serial.printf(" OK: %02d:%02d\n", t.tm_hour, t.tm_min);
            return true;
        }
    }
    Serial.println(" FAILED");
    return false;
}

static uint64_t computeSleepUs() {
    struct tm now;
    if (!getLocalTime(&now, 0)) {
        return 3600ULL * 1000000ULL;
    }

    int cur_min = now.tm_hour * 60 + now.tm_min;
    int target1 = REFRESH_HOUR_1 * 60;
    int target2 = REFRESH_HOUR_2 * 60;

    int sleep_min;
    if (cur_min < target1) {
        sleep_min = target1 - cur_min;
    } else if (cur_min < target2) {
        sleep_min = target2 - cur_min;
    } else {
        sleep_min = (24 * 60 - cur_min) + target1;
    }

    if (sleep_min < 5) sleep_min = 5;

    Serial.printf("Now: %02d:%02d, next refresh in %dh%02dm\n",
                  now.tm_hour, now.tm_min, sleep_min / 60, sleep_min % 60);

    return (uint64_t)sleep_min * 60ULL * 1000000ULL;
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Linky Dashboard ===");

    if (checkResetCommand()) {
        clearConfig();
        Serial.println("Configuration cleared.");
    }

    String ssid, pass, serverUrl;
    bool hasConfig = loadConfig(ssid, pass, serverUrl);

    if (!hasConfig) {
        Serial.println("\nNo configuration found. Starting setup...\n");

        Serial.print("WiFi SSID: ");
        ssid = serialReadLine();

        Serial.print("WiFi Password: ");
        pass = serialReadLine();

        Serial.printf("Server URL [%s]: ", DEFAULT_SERVER_URL);
        serverUrl = serialReadLine();
        if (serverUrl.length() == 0) serverUrl = DEFAULT_SERVER_URL;

        saveConfig(ssid, pass, serverUrl);
        Serial.println("\nConfiguration saved.");
    }

    Serial.printf("Connecting to WiFi: %s\n", ssid.c_str());

    bool connected = false;
    for (int attempt = 1; attempt <= WIFI_MAX_RETRIES; attempt++) {
        Serial.printf("Attempt %d/%d...\n", attempt, WIFI_MAX_RETRIES);
        WiFi.mode(WIFI_STA);
        WiFi.begin(ssid.c_str(), pass.c_str());

        unsigned long start = millis();
        while (WiFi.status() != WL_CONNECTED && (millis() - start) < WIFI_TIMEOUT_MS) {
            delay(250);
            Serial.print(".");
        }
        Serial.println();

        if (WiFi.status() == WL_CONNECTED) {
            connected = true;
            break;
        }
        WiFi.disconnect(true);
        delay(1000);
    }

    if (!connected) {
        Serial.println("WiFi failed. Retrying in 5 minutes...");
        Serial.flush();
        esp_deep_sleep(RETRY_SLEEP_US);
        return;
    }

    Serial.printf("Connected. IP: %s\n", WiFi.localIP().toString().c_str());

    syncNtp();

    uint8_t *buf = (uint8_t *)ps_malloc(DISPLAY_BUFFER_SIZE);
    if (!buf) {
        Serial.println("ERROR: PSRAM allocation failed");
        while (1) delay(1000);
    }

    if (!fetchDisplayBuffer(serverUrl, buf)) {
        Serial.println("Fetch failed. Retrying in 5 minutes...");
        free(buf);
        WiFi.disconnect(true);
        Serial.flush();
        esp_deep_sleep(RETRY_SLEEP_US);
        return;
    }

    DEV_Module_Init();
    EPD_10in85g_Init();
    Serial.println("Rendering...");
    EPD_10in85g_Display(buf);
    EPD_10in85g_Sleep();

    free(buf);

    uint64_t sleepUs = computeSleepUs();

    WiFi.disconnect(true);
    DEV_Module_Exit();

    Serial.printf("Deep sleep...\n");
    Serial.flush();
    esp_deep_sleep(sleepUs);
}

void loop() {
}
