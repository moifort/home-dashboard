"""Electricity domain — Linky consumption (core/mandatory) + power sensors.

The core (Linky HC/HP + talon baseline) is always on; the optional `power`
sub-domain (Cumulus, Lave-linge… generic Z2M power sensors) lives in
electricity/power/ and is iterated by the orchestrator as an optional slice.

The Linky data comes from a Lixee ZLinky_TIC over MQTT (zigbee2mqtt): the
cumulative HCHC/HCHP indexes drive the daily kWh, PAPP the talon, PTEC the live
off-peak state. The point of entry exposes the slice API (init_schema / start /
load_days / build_core / status / is_off_peak), delegating reads to query,
writes to command, the HC/HP + talon math to rules, and transport (MQTT + the
repositories) to infrastructure. Per-domain config (topic, prices, HC windows)
lives here.
"""
import os

from app.system.config import MQTT_HOST
from app.module.format import env_float

TOPIC = os.environ.get("LINKY_MQTT_TOPIC", "zigbee2mqtt/linky")
PRICE_HP = env_float("PRICE_HP", 0.2065)
PRICE_HC = env_float("PRICE_HC", 0.1579)
PRICE_ABO_MONTHLY = env_float("PRICE_ABO_MONTHLY", 15.65)

ENABLED = bool(MQTT_HOST) and bool(TOPIC)


def enabled() -> bool:
    return ENABLED


from app.electricity.command import current_tariff, init_schema, is_off_peak, load_days, start  # noqa: E402
from app.electricity.query import build_core, live_power, status  # noqa: E402

__all__ = [
    "enabled", "init_schema", "start", "load_days", "build_core", "status",
    "is_off_peak", "current_tariff", "live_power", "TOPIC", "ENABLED",
    "PRICE_HP", "PRICE_HC", "PRICE_ABO_MONTHLY",
]
