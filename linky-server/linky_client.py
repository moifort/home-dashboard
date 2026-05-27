"""Conso API client for Linky electricity meter data."""
import logging
import time
from collections import defaultdict
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://conso.boris.sh/api"
USER_AGENT = "linky-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"
MAX_RETRIES = 3


class LinkyApiError(Exception):
    pass


class LinkyAuthError(LinkyApiError):
    pass


def fetch_load_curve(
    token: str, prm: str, start: str, end: str
) -> list[dict]:
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


def parse_hc_windows(windows_str: str) -> list[tuple[int, int, int, int]]:
    """Parse HC windows string into list of (start_h, start_m, end_h, end_m) tuples.

    Example: "23:32-5:32,15:02-17:02" -> [(23, 32, 5, 32), (15, 2, 17, 2)]
    """
    windows = []
    for part in windows_str.split(","):
        start_str, end_str = part.strip().split("-")
        sh, sm = start_str.split(":")
        eh, em = end_str.split(":")
        windows.append((int(sh), int(sm), int(eh), int(em)))
    return windows


def compute_daily_hc_hp(
    api_response: list | dict,
    hc_windows: list[tuple[int, int, int, int]] | None = None,
) -> list[dict]:
    """Aggregate load curve data into daily HC/HP totals.

    Each 30-min interval: energy_Wh = power_W * 0.5
    """
    if hc_windows is None:
        hc_windows = [(23, 32, 5, 32), (15, 2, 17, 2)]

    readings = _extract_readings(api_response)
    if not readings:
        return []

    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"hc_wh": 0.0, "hp_wh": 0.0})

    for reading in readings:
        ts = reading["timestamp"]
        watts = reading["watts"]
        wh = watts * 0.5
        is_hc = _is_off_peak(ts.hour, ts.minute, hc_windows)
        date_key = ts.strftime("%Y-%m-%d")

        if is_hc:
            daily[date_key]["hc_wh"] += wh
        else:
            daily[date_key]["hp_wh"] += wh

    return sorted(
        [
            {
                "date": date,
                "hc_kwh": round(vals["hc_wh"] / 1000, 2),
                "hp_kwh": round(vals["hp_wh"] / 1000, 2),
            }
            for date, vals in daily.items()
        ],
        key=lambda x: x["date"],
    )


def _is_off_peak(hour: int, minute: int, hc_windows: list[tuple[int, int, int, int]]) -> bool:
    t = hour * 60 + minute
    for sh, sm, eh, em in hc_windows:
        start = sh * 60 + sm
        end = eh * 60 + em
        if start > end:
            if t >= start or t < end:
                return True
        else:
            if start <= t < end:
                return True
    return False


def _extract_readings(api_response) -> list[dict]:
    """Normalize various Conso API response formats into a flat list.

    Known formats:
    - {"interval_reading": [{"date": "...", "value": "..."}, ...]}
    - [{"date": "...", "value": "..."}, ...]
    - {"data": [{"date": "...", "value": "..."}, ...]}
    """
    raw_list = []
    if isinstance(api_response, list):
        raw_list = api_response
    elif isinstance(api_response, dict):
        if "interval_reading" in api_response:
            raw_list = api_response["interval_reading"]
        elif "data" in api_response:
            raw_list = api_response["data"]
        else:
            for key in api_response:
                if isinstance(api_response[key], list):
                    raw_list = api_response[key]
                    break

    readings = []
    for entry in raw_list:
        ts = _parse_timestamp(entry)
        watts = _parse_value(entry)
        if ts is not None and watts is not None:
            readings.append({"timestamp": ts, "watts": watts})

    return readings


def _parse_timestamp(entry: dict) -> datetime | None:
    for key in ("date", "timestamp", "dateTime", "start"):
        if key in entry:
            val = entry[key]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
                try:
                    return datetime.strptime(val, fmt)
                except (ValueError, TypeError):
                    continue
    return None


def _parse_value(entry: dict) -> float | None:
    for key in ("value", "watts", "w", "power"):
        if key in entry:
            try:
                return float(entry[key])
            except (ValueError, TypeError):
                continue
    return None
