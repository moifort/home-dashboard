"""REST transport for the UniFi gateway (UCG Ultra / UniFi OS).

Server-side login: POST /api/auth/login holds a TOKEN cookie which is reused on
every call (and re-issued on a 401). The gateway ships a self-signed certificate
so TLS verification is disabled (LAN-only, same technique as the EcoFlow slice's
certifi handling — here we simply trust the local device).

fetch_unifi() returns the raw API payloads (dashboard + active clients + an
optional daily WAN-usage report); all field extraction/formatting lives in the
slice's build_unifi_panel(). Returns None on any error so the panel is omitted.
"""
import logging

import requests
import urllib3

logger = logging.getLogger(__name__)

USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

# The gateway uses a self-signed cert on the LAN; silence the warning once.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# A single Session keeps the TOKEN cookie between refresh cycles; re-login only
# happens on a 401. The slice runs single-threaded (hourly attach), so no lock.
_session: requests.Session | None = None


def _client() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.verify = False
        s.headers["User-Agent"] = USER_AGENT
        _session = s
    return _session


def _login(host: str, user: str, password: str, timeout: float) -> bool:
    """Authenticate; the TOKEN cookie is stored on the shared session."""
    try:
        resp = _client().post(
            f"{host}/api/auth/login",
            json={"username": user, "password": password, "rememberMe": True},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("UniFi login failed: %s", e)
        return False
    return "TOKEN" in _client().cookies


def _get(host: str, path: str, timeout: float):
    """GET a JSON path; raises on HTTP error so the caller can retry on 401."""
    resp = _client().get(f"{host}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(host: str, path: str, body: dict, timeout: float):
    resp = _client().post(f"{host}{path}", json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_daily_usage(host: str, site: str, timeout: float) -> dict | None:
    """Best-effort daily WAN-usage report (for 'yesterday'); None if unavailable.

    Uses the classic stat/report endpoint (POST). A failure here never breaks the
    panel — the slice falls back to the month-only figure.
    """
    try:
        body = {"attrs": ["time", "wan-tx_bytes", "wan-rx_bytes"]}
        return _post(host, f"/proxy/network/api/s/{site}/stat/report/daily.gw", body, timeout)
    except (requests.RequestException, ValueError) as e:
        logger.info("UniFi daily usage report unavailable: %s", e)
        return None


def fetch_unifi(host: str, user: str, password: str, site: str,
                timeout: float = 5) -> dict | None:
    """Fetch the gateway dashboard + active clients (+ daily usage report).

    Logs in on first use; retries once after re-login on a 401. Returns a dict of
    the raw payloads, or None on any network/HTTP error (panel then omitted).
    """
    dash_path = f"/proxy/network/v2/api/site/{site}/aggregated-dashboard"
    clients_path = f"/proxy/network/v2/api/site/{site}/clients/active"

    def _pull() -> dict:
        return {
            "dashboard": _get(host, dash_path, timeout),
            "clients": _get(host, clients_path, timeout),
        }

    # Ensure a session exists; lazily authenticate.
    if "TOKEN" not in _client().cookies and not _login(host, user, password, timeout):
        return None

    try:
        raw = _pull()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            if not _login(host, user, password, timeout):
                return None
            try:
                raw = _pull()
            except requests.RequestException as e2:
                logger.warning("UniFi fetch failed after re-login: %s", e2)
                return None
        else:
            logger.warning("UniFi fetch HTTP error: %s", e)
            return None
    except (requests.RequestException, ValueError) as e:
        logger.warning("UniFi fetch failed: %s", e)
        return None

    raw["daily"] = _fetch_daily_usage(host, site, timeout)
    return raw
