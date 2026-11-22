"""Home lab domain alerts: the "Home lab" status-board section."""
from app.homelab.rules import containers_down
from app.module.format import AlertRule


def _nodes(data):
    return (data.get("homelab") or {}).get("nodes") or []


def _offline(data):
    """A server Komodo cannot reach. Names the first one; the others collapse
    into a '+N' figure."""
    down = [n["name"] for n in _nodes(data) if not n.get("online", True)]
    if not down:
        return None
    return (f"{down[0]} hors ligne", f"+{len(down) - 1}" if len(down) > 1 else "")


def _disk_full(data):
    """A reachable server past its disk threshold (the fullest one only)."""
    full = [n for n in _nodes(data) if n.get("online", True) and n.get("disk_bad")]
    if not full:
        return None
    worst = max(full, key=lambda n: n.get("disk_pct") or 0)
    return (f"Disque {worst['name']} plein", f"{worst['disk_pct']}%")


def _container_down(data):
    """A reachable server with a stopped container. Names the server with the
    most of them; the figure is how many are stopped in all."""
    down = [(containers_down(n), n["name"]) for n in _nodes(data) if n.get("online", True)]
    down = [d for d in down if d[0]]
    if not down:
        return None
    total = sum(count for count, _ in down)
    return (f"Conteneur arrêté sur {max(down)[1]}", str(total) if total > 1 else "")


def _hot(data):
    """A reachable server past the temperature threshold (the hottest one only)."""
    hot = [n for n in _nodes(data) if n.get("online", True) and n.get("temp_bad")]
    if not hot:
        return None
    worst = max(hot, key=lambda n: n.get("temp") or 0)
    return (f"{worst['name']} chaud", f"{worst['temp']}°")


RULES = [
    AlertRule("homelab_offline", _offline, "Home lab", 95, False),
    AlertRule("homelab_container", _container_down, "Home lab", 85, False),
    AlertRule("homelab_hot", _hot, "Home lab", 80, False),
    AlertRule("homelab_disk", _disk_full, "Home lab", 75, False),
]

BOARDS = [
    ("Home lab", lambda data: bool(_nodes(data))),
]
