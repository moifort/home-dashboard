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


def compute_daily_hc_hp(
    api_response: list | dict, hc_start: int = 22, hc_end: int = 6
) -> list[dict]:
    """Aggregate load curve data into daily HC/HP totals.

    The Conso API returns interval_reading entries with:
    - date or timestamp field
    - value in W (average power over interval)

    Each 30-min interval: energy_Wh = power_W * 0.5

    Args:
        api_response: Raw API response (varies in structure)
        hc_start: Hour when off-peak starts (e.g., 22 for 10 PM)
        hc_end: Hour when off-peak ends (e.g., 6 for 6 AM)

    Returns:
        List of {"date": "YYYY-MM-DD", "hc_kwh": float, "hp_kwh": float}
        sorted by date ascending.
    """
    readings = _extract_readings(api_response)
    if not readings:
        return []

    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"hc_wh": 0.0, "hp_wh": 0.0})

    for reading in readings:
        ts = reading["timestamp"]
        watts = reading["watts"]
        wh = watts * 0.5

        hour = ts.hour
        is_hc = _is_off_peak(hour, hc_start, hc_end)

        date_key = ts.strftime("%Y-%m-%d")
        # Slots before hc_end belong to the previous day's night
        if hour < hc_end:
            prev = ts.replace(hour=0, minute=0)
            date_key = prev.strftime("%Y-%m-%d")

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


def _is_off_peak(hour: int, hc_start: int, hc_end: int) -> bool:
    if hc_start > hc_end:
        return hour >= hc_start or hour < hc_end
    return hc_start <= hour < hc_end


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
