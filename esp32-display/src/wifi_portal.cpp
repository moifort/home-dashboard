#include "wifi_portal.h"
#include "config.h"

#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <Preferences.h>

static DNSServer dnsServer;
static WebServer server(80);
static Preferences preferences;

static const char PORTAL_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Arial;max-width:400px;margin:40px auto;padding:0 20px}
input{width:100%;padding:10px;margin:8px 0;box-sizing:border-box;font-size:16px}
button{width:100%;padding:12px;background:#000;color:#fff;border:none;font-size:16px;cursor:pointer}
label{font-weight:bold;display:block;margin-top:16px}</style></head>
<body><h1>Linky Dashboard</h1><p>Configure your WiFi and server.</p>
<form method="POST" action="/save">
<label>WiFi SSID</label><input name="ssid" required>
<label>WiFi Password</label><input name="pass" type="password" required>
<label>Server URL</label><input name="server" value="http://192.168.1.50:5000" required>
<button>Save &amp; Restart</button></form></body></html>
)rawliteral";

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
    Serial.println("Config saved. Restarting...");
    delay(500);
    ESP.restart();
}

void clearConfig() {
    preferences.begin(NVS_NAMESPACE, false);
    preferences.clear();
    preferences.end();
    Serial.println("Config cleared. Restarting...");
    delay(500);
    ESP.restart();
}

static void handleRoot() {
    server.send(200, "text/html", PORTAL_HTML);
}

static void handleSave() {
    String ssid = server.arg("ssid");
    String pass = server.arg("pass");
    String url  = server.arg("server");

    if (ssid.length() == 0 || pass.length() == 0 || url.length() == 0) {
        server.send(400, "text/html",
            "<html><body><h2>Error</h2><p>All fields required.</p>"
            "<a href='/'>Back</a></body></html>");
        return;
    }

    server.send(200, "text/html",
        "<html><body><h2>Saved!</h2><p>Restarting...</p></body></html>");
    delay(200);
    saveConfig(ssid, pass, url);
}

static void handleRedirect() {
    server.sendHeader("Location", "http://192.168.4.1/", true);
    server.send(302, "text/plain", "");
}

void startPortal() {
    WiFi.softAP(AP_SSID);
    IPAddress apIP = WiFi.softAPIP();
    Serial.printf("AP started: %s — IP: %s\n", AP_SSID, apIP.toString().c_str());

    dnsServer.start(53, "*", apIP);

    server.on("/", handleRoot);
    server.on("/save", HTTP_POST, handleSave);
    server.on("/generate_204", handleRedirect);
    server.on("/fwlink", handleRedirect);
    server.on("/hotspot-detect.html", handleRedirect);
    server.on("/connecttest.txt", handleRedirect);
    server.onNotFound(handleRedirect);

    server.begin();
    Serial.println("Captive portal started");
}

void portalLoop() {
    dnsServer.processNextRequest();
    server.handleClient();
}
