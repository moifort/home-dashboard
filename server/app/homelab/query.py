"""Home lab domain queries (read side): read Komodo, attach the panel."""
import time
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
    nodes = [
        rules.build_node(s, komodo_client.fetch_history(URL, API_KEY, API_SECRET, s["id"], since_ms), now_ms)
        for s in servers if s.get("state") != "Disabled"
    ]
    if not nodes:
        return
    data["homelab"] = rules.build_panel(nodes)
    _last_homelab_time = datetime.now(PARIS_TZ).isoformat()


def status() -> dict:
    from app.homelab import ENABLED

    return {"homelab_enabled": ENABLED, "last_homelab": _last_homelab_time}
