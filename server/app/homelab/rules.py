"""Home lab business rules: pure functions (no IO).

Turn Komodo's servers and container counts, plus each server's temperature,
into the render-ready panel:
    {"online": 3, "total": 4, "nodes": [
        {"name": "pi-nas", "online": True, "temp": 52, "temp_bad": False,
         "mem_pct": 31, "mem_bad": False, "disk_pct": 91, "disk_bad": True,
         "up": 3, "containers": 4}, ...]}
A figure Komodo or the exporter did not give is None.
"""
MAX_NODES = 6            # the screen fits six server cards
MEM_WARN_PCT = 90.0      # used when the server carries no Komodo memory threshold
DISK_WARN_PCT = 90.0     # same, for the disk
TEMP_WARN_C = 70.0       # a Raspberry Pi throttles at 80 °C


def _rounded(value):
    return None if value is None else round(value)


def build_node(server: dict, containers=None, temp=None) -> dict:
    """One server's card. `server` comes from komodo_client.fetch_servers,
    `containers` is its (running, total) pair, `temp` its temperature in °C."""
    mem, disk = server.get("mem_pct"), server.get("disk_pct")
    up, total = containers or (None, None)
    return {
        "name": server["name"],
        "online": server.get("state") == "Ok",
        "temp": _rounded(temp),
        "temp_bad": temp is not None and temp >= TEMP_WARN_C,
        "mem_pct": _rounded(mem),
        "mem_bad": mem is not None and mem >= (server.get("mem_warning") or MEM_WARN_PCT),
        "disk_pct": _rounded(disk),
        "disk_bad": disk is not None and disk >= (server.get("disk_warning") or DISK_WARN_PCT),
        "up": up,
        "containers": total,
    }


def containers_down(node: dict) -> int:
    return max(0, (node.get("containers") or 0) - (node.get("up") or 0))


def has_problem(node: dict) -> bool:
    return (not node["online"] or node.get("disk_bad") or node.get("temp_bad")
            or node.get("mem_bad") or containers_down(node) > 0)


def build_panel(nodes: list) -> dict:
    """The panel: every server counted, at most MAX_NODES shown. Names sort the
    cards so a server keeps its place; only when there are more servers than
    cards do the ones with a problem come first."""
    nodes = sorted(nodes, key=lambda n: n["name"].lower())
    shown = nodes
    if len(nodes) > MAX_NODES:
        shown = sorted(nodes, key=lambda n: not has_problem(n))[:MAX_NODES]
    return {"online": sum(1 for n in nodes if n["online"]), "total": len(nodes), "nodes": shown}
