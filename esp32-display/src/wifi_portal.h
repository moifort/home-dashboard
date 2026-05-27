#ifndef __WIFI_PORTAL_H_
#define __WIFI_PORTAL_H_

#include <Arduino.h>

/**
 * Load WiFi and server config from NVS.
 * Populates the out-params if found.
 * Returns true if all three values exist.
 */
bool loadConfig(String &ssid, String &pass, String &serverUrl);

/**
 * Save WiFi and server config to NVS, then restart.
 */
void saveConfig(const String &ssid, const String &pass, const String &serverUrl);

/**
 * Clear all config from NVS, then restart.
 */
void clearConfig();

/**
 * Start the captive portal (AP + DNS + web server).
 * This function sets up the AP and servers but does NOT block.
 * The caller must call portalLoop() repeatedly.
 */
void startPortal();

/**
 * Process DNS requests in the main loop.
 * Must be called repeatedly when in portal mode.
 */
void portalLoop();

#endif
