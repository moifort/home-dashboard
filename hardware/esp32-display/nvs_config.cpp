#include "nvs_config.h"
#include <Preferences.h>

static Preferences preferences;

bool loadConfig(String &ssid, String &pass, String &serverUrl) {
    preferences.begin(NVS_NAMESPACE, true);
    ssid      = preferences.getString("wifi_ssid", "");
    pass      = preferences.getString("wifi_pass", "");
    serverUrl = preferences.getString("server_url", "");
    preferences.end();
    return ssid.length() > 0 && pass.length() > 0 && serverUrl.length() > 0;
}

void saveConfig(const String &ssid, const String &pass, const String &serverUrl) {
    preferences.begin(NVS_NAMESPACE, false);
    preferences.putString("wifi_ssid", ssid);
    preferences.putString("wifi_pass", pass);
    preferences.putString("server_url", serverUrl);
    preferences.end();
}

void clearConfig() {
    preferences.begin(NVS_NAMESPACE, false);
    preferences.clear();
    preferences.end();
}
