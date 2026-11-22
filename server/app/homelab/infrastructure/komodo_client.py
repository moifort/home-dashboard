"""REST transport for the Komodo Core API (read-only).

Every call is a POST authenticated by an API key pair (X-Api-Key / X-Api-Secret,
created in Komodo under Settings > Profile > API Keys). Komodo 2 exposes one route
per request (`/read/ListServers`, the params as the body); Komodo 1 has a single
`/read` route with a typed body, used as a fallback when the first form is not
found.

Two requests feed the panel: `ListServers` carries each server's state, its
alert thresholds and its latest stats (memory, disk), and
`ListAllDockerContainers` every container with its server and state.
"""
import logging

import requests

logger = logging.getLogger(__name__)

TIMEOUT_S = 10

_session: requests.Session | None = None
_legacy_route = False


def _client() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _read(url: str, key: str, secret: str, name: str, params: dict):
    global _legacy_route
    headers = {"X-Api-Key": key, "X-Api-Secret": secret}
    if not _legacy_route:
        resp = _client().post(f"{url}/read/{name}", json=params, headers=headers, timeout=TIMEOUT_S)
        if resp.status_code not in (404, 405):
            resp.raise_for_status()
            return resp.json()
        _legacy_route = True
    resp = _client().post(f"{url}/read", json={"type": name, "params": params},
                          headers=headers, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _pct(used, total):
    return None if not total or used is None else used / total * 100


def fetch_servers(url: str, key: str, secret: str) -> list | None:
    """Every server Komodo knows as {"id", "name", "state", "mem_pct", "disk_pct",
    "mem_warning", "disk_warning"} (state: "Ok", "NotOk" or "Disabled"; the
    percentages are None while Komodo has no stats). None on any error."""
    try:
        items = _read(url, key, secret, "ListServers", {})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Komodo ListServers failed: %s", exc)
        return None
    servers = []
    for item in items or []:
        info = item.get("info") or {}
        stats, limits = info.get("stats") or {}, info.get("alerting_thresholds") or {}
        servers.append({
            "id": item.get("id"), "name": item.get("name") or "",
            "state": info.get("state"),
            "mem_pct": _pct(stats.get("mem_used_gb"), stats.get("mem_total_gb")),
            "disk_pct": _pct(stats.get("disk_used_gb"), stats.get("disk_total_gb")),
            "mem_warning": limits.get("mem_warning"),
            "disk_warning": limits.get("disk_warning"),
        })
    return servers


def fetch_containers(url: str, key: str, secret: str) -> dict | None:
    """{server id: (running, total)} over every container. None on any error."""
    try:
        items = _read(url, key, secret, "ListAllDockerContainers", {"servers": []})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Komodo ListAllDockerContainers failed: %s", exc)
        return None
    counts = {}
    for item in items or []:
        running, total = counts.get(item.get("server_id"), (0, 0))
        counts[item.get("server_id")] = (running + (item.get("state") == "running"), total + 1)
    return counts
