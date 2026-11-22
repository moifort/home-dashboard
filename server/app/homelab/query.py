"""Home lab domain queries (read side): read Komodo, attach the panel."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.homelab import rules
from app.homelab.infrastructure import komodo_client
from app.system.config import PARIS_TZ

_last_homelab_time = ""


def attach(data: dict):
    """List the servers, read each one's last 24 hours, attach the panel.

    Disabled servers are left out. When Komodo cannot be reached the key is left
    unset, so the row is simply omitted.
    """
    global _last_homelab_time
    from app.homelab import API_KEY, API_SECRET, URL

    servers = komodo_client.fetch_servers(URL, API_KEY, API_SECRET)
    if not servers:
        return
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - rules.HOURS * rules.HOUR_MS
    servers = [s for s in servers if s.get("state") != "Disabled"]
    if not servers:
        return

    def node(server):
        records = komodo_client.fetch_history(URL, API_KEY, API_SECRET, server["id"], since_ms, now_ms)
        return rules.build_node(server, records, now_ms)

    # One thread per server: 8 pages each, read one after the other, would keep
    # the battery-powered screen waiting for its image.
    with ThreadPoolExecutor(max_workers=len(servers)) as pool:
        nodes = list(pool.map(node, servers))
    data["homelab"] = rules.build_panel(nodes)
    _last_homelab_time = datetime.now(PARIS_TZ).isoformat()


def status() -> dict:
    from app.homelab import ENABLED

    return {"homelab_enabled": ENABLED, "last_homelab": _last_homelab_time}
