"""Home lab domain commands (write side): the background reader.

A daemon thread reads Komodo and the temperature exporters every REFRESH_S and
keeps the panel in memory; the render path only picks up that copy, so a slow or
silent server never delays the battery-powered screen. Komodo holds the state
itself, so there is still no table.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.homelab import rules
from app.homelab.infrastructure import komodo_client, node_exporter

logger = logging.getLogger(__name__)

REFRESH_S = 5 * 60         # a temperature a few minutes old is fresh enough
STALE_S = 6 * REFRESH_S    # after half an hour without a read the row is dropped rather than shown stale

_cache: tuple | None = None  # (panel, read at, epoch seconds)


def init_schema():
    """No table: Komodo keeps the stats."""
    return None


def refresh() -> dict | None:
    """Read Komodo and the exporters now and cache the panel. Disabled servers
    are left out. Returns None, leaving the previous copy in place, when Komodo
    cannot be reached or has no server."""
    global _cache
    from app.homelab import API_KEY, API_SECRET, TEMP_URLS, URL

    servers = komodo_client.fetch_servers(URL, API_KEY, API_SECRET)
    servers = [s for s in servers or [] if s.get("state") != "Disabled"]
    if not servers:
        return None
    containers = komodo_client.fetch_containers(URL, API_KEY, API_SECRET) or {}

    def temp(server):
        url = TEMP_URLS.get(server["name"])
        return node_exporter.fetch_temp(url) if url else None

    with ThreadPoolExecutor(max_workers=len(servers)) as pool:  # one thread per server
        temps = list(pool.map(temp, servers))
    panel = rules.build_panel([rules.build_node(s, containers.get(s["id"]), t)
                               for s, t in zip(servers, temps)])
    _cache = (panel, time.time())
    return panel


def current() -> dict | None:
    """The cached panel while it is fresh, else None."""
    if _cache and time.time() - _cache[1] < STALE_S:
        return _cache[0]
    return None


def last_read() -> float | None:
    """Epoch seconds of the last successful read."""
    return _cache[1] if _cache else None


def _loop():
    while True:
        try:
            refresh()
        except Exception:
            logger.exception("home lab refresh failed")
        time.sleep(REFRESH_S)


def start():
    """Start the background reader (the server calls start() on every domain,
    enabled or not)."""
    from app.homelab import ENABLED

    if not ENABLED:
        return None
    threading.Thread(target=_loop, name="homelab-komodo", daemon=True).start()
