"""REST transport for the Komodo Core API (read-only).

Every call is a POST authenticated by an API key pair (X-Api-Key / X-Api-Secret,
created in Komodo under Settings > Profile > API Keys). Komodo 2 exposes one route
per request (`/read/ListServers`, the params as the body); Komodo 1 has a single
`/read` route with a typed body, used as a fallback when the first form is not
found.

Historical stats come 200 records per page, newest first, on the granularity
asked: one record per minute here, so 24 hours are 8 pages per server. A coarser
step would be cheaper but would miss any spike shorter than the step.
"""
import logging

import requests

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
GRANULARITY = "1-min"
MAX_PAGES = 10  # 24 h at one record per minute fit in 8 pages of 200

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


def fetch_servers(url: str, key: str, secret: str) -> list | None:
    """Every server Komodo knows as {"id", "name", "state", "disk_warning"}
    (state: "Ok", "NotOk" or "Disabled"). None on any error."""
    try:
        items = _read(url, key, secret, "ListServers", {})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Komodo ListServers failed: %s", exc)
        return None
    servers = []
    for item in items or []:
        info = item.get("info") or {}
        servers.append({
            "id": item.get("id"), "name": item.get("name") or "",
            "state": info.get("state"),
            "disk_warning": (info.get("alerting_thresholds") or {}).get("disk_warning"),
        })
    return servers


def fetch_history(url: str, key: str, secret: str, server_id: str, since_ms: int) -> list:
    """A server's stat records since since_ms (unordered). Returns what was read
    before any error, so one failing server only loses its own history."""
    records, page = [], 0
    try:
        for _ in range(MAX_PAGES):
            body = _read(url, key, secret, "GetHistoricalServerStats",
                         {"server": server_id, "granularity": GRANULARITY, "page": page})
            stats = body.get("stats") or []
            records += stats
            page = body.get("next_page")
            if page is None or not stats or min(r.get("ts", 0) for r in stats) <= since_ms:
                break
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Komodo history failed for %s: %s", server_id, exc)
    return [r for r in records if r.get("ts", 0) > since_ms]
