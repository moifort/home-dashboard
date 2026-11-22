"""Home lab domain: the servers Komodo watches (the `home lab` row of the arcade UI).

Komodo already polls every server, so this domain owns no table: a background
reader asks the Komodo Core API for the servers (state, memory, disk) and their
containers every few minutes and keeps the result in memory for the render.
Komodo measures no temperature: it is read, when configured, from a Prometheus
node exporter running on each server (HOMELAB_TEMP_URLS).
The point of entry exposes the uniform slice API (enabled / init_schema / start /
attach / status). Remove the whole folder to drop it.
"""
import os

URL = os.environ.get("KOMODO_URL", "").rstrip("/")
API_KEY = os.environ.get("KOMODO_API_KEY", "")
API_SECRET = os.environ.get("KOMODO_API_SECRET", "")

ENABLED = bool(URL and API_KEY and API_SECRET)


def _parse_temp_urls(raw: str) -> dict:
    """"pi-nas=http://host:9100/metrics;pi-dns=http://…" → {server name: url}."""
    urls = {}
    for part in raw.split(";"):
        name, sep, url = part.partition("=")
        if sep and name.strip() and url.strip():
            urls[name.strip()] = url.strip()
    return urls


# Komodo server name → metrics URL of the node exporter running on that server.
TEMP_URLS = _parse_temp_urls(os.environ.get("HOMELAB_TEMP_URLS", ""))


def enabled() -> bool:
    return ENABLED


from app.homelab.command import init_schema, start  # noqa: E402
from app.homelab.query import attach, status  # noqa: E402

__all__ = ["enabled", "init_schema", "start", "attach", "status",
           "ENABLED", "URL", "API_KEY", "API_SECRET", "TEMP_URLS"]
