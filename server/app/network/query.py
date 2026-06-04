"""Network domain queries (read side): fetch + snapshot + attach the panel."""
import logging
from datetime import datetime

from app.system.config import PARIS_TZ
from app.network import command
from app.network.infrastructure import repository
from app.network.infrastructure.unifi_client import fetch_unifi
from app.network.rules import TREND_DAYS, _TREND_COLUMNS, build_unifi_panel, compute_trend

logger = logging.getLogger(__name__)

_last_unifi_time = ""


def attach(data: dict):
    """Fetch gateway stats, snapshot today's values, attach the panel + trends.

    On any failure the key is left unset, so the panel is simply omitted.
    """
    global _last_unifi_time
    from app.network import HOST, PASSWORD, SITE, SSID_IOT, SSID_MAIN, USERNAME

    raw = fetch_unifi(HOST, USERNAME, PASSWORD, SITE)
    if not raw:
        return
    panel = build_unifi_panel(raw, {"iot": SSID_IOT, "main": SSID_MAIN})
    if not panel:
        return
    command.snapshot(panel.pop("_snap"))
    for column, key in _TREND_COLUMNS:
        panel[key] = _compute_trend(column)
    data["unifi"] = panel
    _last_unifi_time = datetime.now(PARIS_TZ).isoformat()


def _compute_trend(column: str) -> float | None:
    """Latest completed day vs the average of up to TREND_DAYS prior days, in %."""
    return compute_trend(repository.trend_values(column, TREND_DAYS + 1))


def status() -> dict:
    from app.network import ENABLED

    return {"unifi_enabled": ENABLED, "last_unifi": _last_unifi_time}
