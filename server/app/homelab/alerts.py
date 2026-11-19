"""Home lab domain alerts: the "Home lab" status-board section."""
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


RULES = [
    AlertRule("homelab_offline", _offline, "Home lab", 95, False),
    AlertRule("homelab_disk", _disk_full, "Home lab", 75, False),
]

BOARDS = [
    ("Home lab", lambda data: bool(_nodes(data))),
]
