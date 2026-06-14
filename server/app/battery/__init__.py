"""Battery domain — ESP32 autonomy tracking (no extra sensor).

The firmware reports its RTC bootCount, reset reason and fail count as query
params on the GET /display pull; this domain logs each pull into battery cycles
(a run on one charge, bounded by power-on events — alimentation rétablie après
recharge / batterie vide) and surfaces "jours depuis la dernière charge" in the
Home panel plus average / record autonomy on /status. It ingests through the
server's generic `record_pull` hook (no MQTT), so it owns no broker config.
Remove the whole folder to drop the battery tracking.
"""
import os

# Pure telemetry over the existing /display pull — no external dependency, so it
# is on by default; set BATTERY_MONITOR=false to disable.
ENABLED = os.environ.get("BATTERY_MONITOR", "true").strip().lower() in (
    "1", "true", "yes", "on",
)


def enabled() -> bool:
    return ENABLED


from app.battery.command import init_schema, start, record_pull  # noqa: E402
from app.battery.query import attach, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status", "record_pull",
    "ENABLED",
]
