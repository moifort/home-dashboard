"""Home lab domain commands (write side): the background Komodo reader.

Reading 24 hours of one-minute records for every server takes Komodo several
seconds, far too long to do while the battery-powered screen waits for its image.
A daemon thread therefore reads Komodo every REFRESH_S and keeps the panel in
memory; the render path only picks up that copy. Komodo stores the history
itself, so there is still no table.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.homelab import rules
from app.homelab.infrastructure import komodo_client

logger = logging.getLogger(__name__)

REFRESH_S = 30 * 60        # the screen refreshes every two hours: half an hour old is fresh enough
STALE_S = 3 * REFRESH_S    # after three missed reads the row is dropped rather than shown stale

_cache: tuple | None = None  # (panel, read at, epoch seconds)


def init_schema():
    """No table: Komodo keeps the stats."""
    return None


def refresh() -> dict | None:
    """Read Komodo now and cache the panel. Disabled servers are left out.
    Returns None, leaving the previous copy in place, when Komodo cannot be
    reached or has no server."""
    global _cache
    from app.homelab import API_KEY, API_SECRET, URL

    servers = komodo_client.fetch_servers(URL, API_KEY, API_SECRET)
    servers = [s for s in servers or [] if s.get("state") != "Disabled"]
    if not servers:
        return None
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - rules.HOURS * rules.HOUR_MS

    def node(server):
        records = komodo_client.fetch_history(URL, API_KEY, API_SECRET, server["id"], since_ms, now_ms)
        return rules.build_node(server, records, now_ms)

    with ThreadPoolExecutor(max_workers=len(servers)) as pool:  # one thread per server
        panel = rules.build_panel(list(pool.map(node, servers)))
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
