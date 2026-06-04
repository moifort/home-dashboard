"""Network domain — UniFi network-quality panel ("Réseau").

Turns the gateway payloads into the render-ready panel (internet/Wi-Fi quality,
clients per SSID, top clients, data usage). Fetched live on the hourly refresh; a
tiny daily snapshot table (daily_unifi) feeds the ▲▼ trends (7-day average, no
backfill). The point of entry exposes the uniform slice API (enabled /
init_schema / start / attach / status), delegating reads to query, lifecycle to
command, and the payload→panel math to rules. Remove the whole folder to drop it.
"""
import os

HOST = os.environ.get("UNIFI_HOST", "https://192.168.1.1").rstrip("/")
USERNAME = os.environ.get("UNIFI_USERNAME", "")
PASSWORD = os.environ.get("UNIFI_PASSWORD", "")
SITE = os.environ.get("UNIFI_SITE", "default")
SSID_IOT = os.environ.get("UNIFI_SSID_IOT", "")
SSID_MAIN = os.environ.get("UNIFI_SSID_MAIN", "")

ENABLED = bool(PASSWORD)


def enabled() -> bool:
    return ENABLED


from app.network.command import init_schema, start  # noqa: E402
from app.network.query import attach, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status",
    "ENABLED", "HOST", "USERNAME", "PASSWORD", "SITE", "SSID_IOT", "SSID_MAIN",
]
