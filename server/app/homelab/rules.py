"""Home lab business rules: pure functions (no IO).

Turn Komodo's server list and stat records into the render-ready panel:
    {"online": 3, "total": 4, "nodes": [
        {"name": "pi-nas", "online": True, "cpu": [24 × % | None],
         "mem": [24 × % | None], "disk_pct": 91, "disk_bad": True}, ...]}
`cpu` and `mem` are the last 24 hours, oldest first; each value is the hour's
highest reading, None when Komodo has no record for that hour.
"""
HOURS = 24
HOUR_MS = 3_600_000
MAX_NODES = 4            # the screen has four columns for servers
DISK_WARN_PCT = 90.0     # used when the server carries no Komodo disk threshold


def hourly_max(samples, now_ms: int) -> list:
    """Fold (ts_ms, value) samples into HOURS columns ending at now_ms."""
    out = [None] * HOURS
    for ts, value in samples:
        if value is None:
            continue
        col = HOURS - 1 - max(0, now_ms - ts) // HOUR_MS
        if 0 <= col < HOURS:
            out[col] = value if out[col] is None else max(out[col], value)
    return [None if v is None else round(v) for v in out]


def _pct(used, total):
    return None if not total or used is None else used / total * 100


def build_node(server: dict, records: list, now_ms: int) -> dict:
    """One server's column. `server` is {"name", "state", "disk_warning"};
    `records` are Komodo SystemStatsRecord dicts in any order."""
    records = [r for r in records if isinstance(r.get("ts"), (int, float))]
    latest = max(records, key=lambda r: r["ts"], default={})
    disk = _pct(latest.get("disk_used_gb"), latest.get("disk_total_gb"))
    warn = server.get("disk_warning") or DISK_WARN_PCT
    return {
        "name": server["name"],
        "online": server.get("state") == "Ok",
        "cpu": hourly_max([(r["ts"], r.get("cpu_perc")) for r in records], now_ms),
        "mem": hourly_max([(r["ts"], _pct(r.get("mem_used_gb"), r.get("mem_total_gb")))
                           for r in records], now_ms),
        "disk_pct": None if disk is None else round(disk),
        "disk_bad": disk is not None and disk >= warn,
    }


def has_problem(node: dict) -> bool:
    return not node["online"] or node["disk_bad"]


def build_panel(nodes: list) -> dict:
    """The panel: every server counted, at most MAX_NODES shown. Names sort the
    columns so a server keeps its place; only when there are more servers than
    columns do the ones with a problem come first."""
    nodes = sorted(nodes, key=lambda n: n["name"].lower())
    shown = nodes
    if len(nodes) > MAX_NODES:
        shown = sorted(nodes, key=lambda n: not has_problem(n))[:MAX_NODES]
    return {"online": sum(1 for n in nodes if n["online"]), "total": len(nodes), "nodes": shown}
