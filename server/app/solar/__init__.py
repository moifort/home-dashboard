"""Solar domain — EcoFlow PowerStream production ("Production solaire").

The PowerStream exposes only instantaneous PV watts (no energy counter), so the
command side integrates the heartbeat power into daily kWh. The point of entry
exposes the uniform slice API (enabled / init_schema / start / attach / status),
delegating reads to query, the integrator/listener to command, the panel math to
rules, and transport (API client, MQTT, protobuf) to infrastructure. Remove the
whole folder to drop solar.
"""
import os

EMAIL = os.environ.get("ECOFLOW_EMAIL", "")
PASSWORD = os.environ.get("ECOFLOW_PASSWORD", "")
DEVICE_SN = os.environ.get("ECOFLOW_DEVICE_SN", "")
API_HOST = os.environ.get("ECOFLOW_API_HOST", "api-e.ecoflow.com")
# Electricity price used to value the produced solar energy (own copy so the
# domain stays self-contained and removable).
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))

ENABLED = bool(EMAIL and PASSWORD and DEVICE_SN)


def enabled() -> bool:
    return ENABLED


from app.solar.command import init_schema, start  # noqa: E402
from app.solar.query import attach, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "attach", "status",
    "ENABLED", "EMAIL", "PASSWORD", "DEVICE_SN", "API_HOST", "PRICE_HP",
]
