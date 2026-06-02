"""Conso REST API transport: fetch the 30-min consumption load curve."""
import logging
import time

import requests

from ..client import LinkyApiError, LinkyAuthError

logger = logging.getLogger(__name__)

API_BASE = "https://conso.boris.sh/api"
USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"
MAX_RETRIES = 3


def fetch_load_curve(token: str, prm: str, start: str, end: str) -> list[dict]:
    """Fetch consumption load curve (30-min intervals) from Conso API.

    Args:
        token: JWT bearer token
        prm: 14-digit meter identifier
        start: Start date YYYY-MM-DD (inclusive)
        end: End date YYYY-MM-DD (exclusive)

    Returns:
        Raw API response data (list of interval readings).
    """
    url = f"{API_BASE}/consumption_load_curve"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    params = {"prm": prm, "start": start, "end": end}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code in (401, 403):
                raise LinkyAuthError(f"Authentication failed: {resp.status_code}")
            if resp.status_code == 400:
                raise LinkyApiError(f"Bad request: {resp.text[:200]}")
            if resp.status_code == 429:
                logger.warning("Rate limited, backing off 60s")
                time.sleep(60)
                continue
            resp.raise_for_status()
            return resp.json()
        except LinkyAuthError:
            raise
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                delay = 2 ** (attempt + 1)
                logger.warning("API request failed (%s), retrying in %ds", e, delay)
                time.sleep(delay)
            else:
                raise LinkyApiError(f"API request failed after {MAX_RETRIES} attempts: {e}") from e

    raise LinkyApiError("Max retries exceeded")
