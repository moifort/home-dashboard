"""Power sub-domain commands (write side): schema init + per-sensor integrators.

Each configured topic gets its own MQTT listener and its own shared
DailyEnergyIntegrator instance keyed by slug — no shared state, no lock. The
off-peak split (`_hc_wh`) rides on top of the integrator: every increment also
lands in the day's off-peak Wh when the meter is currently off-peak
(electricity.is_off_peak(), the live PTEC).

SENSORS/ENABLED are read through the package at call time so tests (and
gen_preview) can monkeypatch them on `app.electricity.power`.
"""
import logging
from datetime import datetime, timedelta

from app.system.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ
from app.module.integrator import DailyEnergyIntegrator
from app.electricity import is_off_peak
from app.electricity.power.infrastructure import repository
from app.electricity.power.infrastructure.mqtt import PowerMqttListener

logger = logging.getLogger(__name__)

# Per-sensor integration state (power -> daily kWh). Only each sensor's MQTT
# listener thread touches its own entries, so no lock is needed. _hc_wh is the
# off-peak split the shared integrator doesn't know about: its persists can lag
# the split by at most the current sample (caught up 30s later; the day-end
# flush is exact because the last sample's split lands before the rollover).
_integrators: dict = {}
_hc_wh: dict = {}
_last_report: dict = {}


def init_schema():
    """Create the shared daily_power table and migrate legacy tables once."""
    repository.init_schema()


def _make_on_power(slug: str):
    """Build the MQTT callback that integrates one sensor's power into daily kWh."""

    def _flush(date: str, wh: float):
        repository.upsert_power(slug, date, wh, _hc_wh.get(slug, 0.0))

    def _reload(date: str) -> float:
        tomorrow = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = repository.get_cached_power(slug, date, tomorrow)
        hc = existing[0]["hc_kwh"] if existing else None
        _hc_wh[slug] = hc * 1000 if hc is not None else 0.0
        return existing[0]["cons_kwh"] * 1000 if existing else 0.0

    integrator = _integrators[slug] = DailyEnergyIntegrator(_flush, _reload)

    def _on_power(watts: float):
        now = datetime.now(PARIS_TZ)
        inc = integrator.feed(watts, now)
        # Off-peak as the meter sees it (the ZLinky's live PTEC): the whole
        # interval is attributed to `now` (as the day already is).
        if inc and is_off_peak():
            _hc_wh[slug] = _hc_wh.get(slug, 0.0) + inc
        _last_report[slug] = now.isoformat()

    return _on_power


def start():
    """Start one MQTT listener per configured sensor, else log and do nothing."""
    from app.electricity import power

    if not power.ENABLED:
        logger.info("Power sensors disabled (set MQTT_HOST + POWER_SENSORS to enable)")
        return None
    listeners = []
    for s in power.SENSORS:
        listener = PowerMqttListener(
            s.slug, MQTT_HOST, MQTT_PORT, s.topic, MQTT_USERNAME, MQTT_PASSWORD,
            _make_on_power(s.slug),
        )
        listener.start()
        listeners.append(listener)
        logger.info("Power MQTT listener started (%s) on %s:%d (%s)",
                    s.slug, MQTT_HOST, MQTT_PORT, s.topic)
    return listeners
