"""Reads a server's temperature from its Prometheus node exporter.

Komodo measures no temperature, so each server may run a node exporter (thermal
zone collector); its text page carries one line per sensor:
    node_thermal_zone_temp{type="cpu-thermal",zone="0"} 47.712
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)

TIMEOUT_S = 4
_LINE = re.compile(r"^node_(?:thermal_zone_temp|hwmon_temp_celsius)(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$", re.M)


def parse_temp(text: str) -> float | None:
    """The hottest sensor of a metrics page, in °C."""
    values = []
    for raw in _LINE.findall(text or ""):
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return max(values) if values else None


def fetch_temp(url: str) -> float | None:
    """The server's temperature in °C, None when the exporter cannot be read."""
    try:
        resp = requests.get(url, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("node exporter %s failed: %s", url, exc)
        return None
    return parse_temp(resp.text)
