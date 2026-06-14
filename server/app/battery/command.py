"""Battery domain commands (write side): schema init + the /display pull recorder.

Unlike the MQTT slices, this domain ingests through the firmware's GET /display
query params (boot/reason/fail), recorded by `record_pull` which the server calls
generically on every pull. There is no background listener, so `start()` is a
no-op.
"""
import logging
from datetime import datetime

from app.battery import rules
from app.battery.infrastructure import repository

logger = logging.getLogger(__name__)

# Runtime state for /status: the last telemetry the firmware reported.
last_report: dict = {}


def init_schema():
    """Create the battery_cycles table (idempotent)."""
    repository.init_schema()


def start():
    """No background listener: telemetry arrives on the /display pull."""
    from app.battery import ENABLED

    if not ENABLED:
        logger.info("Battery monitor disabled (set BATTERY_MONITOR=true to enable)")
        return None
    logger.info("Battery monitor enabled (telemetry via /display query params)")
    return None


def _qs_int(params: dict, key: str) -> int | None:
    """Read a single int from a parse_qs dict ({key: [value]}), or None."""
    values = params.get(key)
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def record_pull(params: dict, now: datetime):
    """Record one /display pull's firmware telemetry into the current battery
    cycle. A power-on (recharge / first boot) opens a new cycle; a deep-sleep wake
    extends the current one. No `boot` param (an un-flashed firmware) → no-op."""
    global last_report

    boot = _qs_int(params, "boot")
    if boot is None:
        return  # firmware doesn't report telemetry yet — nothing to track
    reason = _qs_int(params, "reason")
    fail = _qs_int(params, "fail")

    last = repository.get_last_cycle()
    if last is None or rules.is_power_on(reason, boot, last.get("last_boot")):
        repository.insert_cycle(now.isoformat(), boot)
    else:
        repository.update_cycle(last["id"], now.isoformat(), last["wakes"] + 1, boot)

    last_report = {"boot": boot, "reason": reason, "fail": fail, "at": now.isoformat()}
