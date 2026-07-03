"""Power sub-domain of electricity — generic MQTT power sensors (config-driven).

Every Z2M device that exposes only instantaneous power (W) and no energy counter
is declared in a single env var and integrated the same way — report a power ->
integrate into daily kWh -> one bottom-table row each.

Config: POWER_SENSORS = "topic:Display Name;topic2:Other Name" (`;` separates
sensors, the first `:` of each entry separates the MQTT topic from its label).
Broker host/port/credentials are shared (system.config); this sub-domain owns the
topics.

**Grouping**: several topics that share the same label are summed into one
bottom-table row (e.g. four plugs all named `Salon` -> a single `Salon` total).
Each topic keeps its own MQTT listener and integrator (no shared state, no lock);
the sum is computed at display time over the group's per-topic daily series. A
lone sensor stores under `_slugify(name)` (unchanged, history preserved); the
members of a multi-topic group get a per-topic suffix so they never collide.
"""
import logging
import os
from collections import Counter, namedtuple
from datetime import datetime, timedelta

from app.system.config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME, PARIS_TZ
from app.module.format import format_energy_kwh
from app.module.integrator import DailyEnergyIntegrator
from app.module.sensors import parse_entries, slugify as _slugify, topic_suffixed_slug
from app.electricity import is_off_peak
from app.electricity.power.infrastructure import repository
from app.electricity.power.infrastructure.mqtt import PowerMqttListener

logger = logging.getLogger(__name__)

Sensor = namedtuple("Sensor", "slug topic name")


def _parse_sensors(raw: str) -> list:
    """Parse "topic:Name;topic2:Name 2" into a list of Sensor; skip malformed.

    Topics sharing a name form a group summed under that label. A lone name keeps
    the bare `_slugify(name)` storage slug (backward compatible); each member of a
    multi-topic group gets a `_slugify(name)-_slugify(topic)` slug so they don't
    collide. The group total is the sum of its members, so which member owns which
    slug is irrelevant to the displayed value.
    """
    parsed = parse_entries(raw, "POWER_SENSORS")  # (topic, name), deduped by topic
    name_counts = Counter(name for _, name in parsed)
    return [
        Sensor(topic_suffixed_slug(name, topic) if name_counts[name] > 1 else _slugify(name),
               topic, name)
        for topic, name in parsed
    ]


def _groups(sensors: list) -> list:
    """Group sensors by display name, preserving each name's first-appearance
    order. Returns an ordered list of (name, [slug, ...])."""
    by_name: dict = {}
    order = []
    for s in sensors:
        if s.name not in by_name:
            by_name[s.name] = []
            order.append(s.name)
        by_name[s.name].append(s.slug)
    return [(name, by_name[name]) for name in order]


POWER_SENSORS = os.environ.get("POWER_SENSORS", "")
SENSORS = _parse_sensors(POWER_SENSORS)
ENABLED = bool(MQTT_HOST) and bool(SENSORS)

# Per-sensor integration state (power -> daily kWh). Only each sensor's MQTT
# listener thread touches its own entries, so no lock is needed. _hc_wh is the
# off-peak split the shared integrator doesn't know about: its persists can lag
# the split by at most the current sample (caught up 30s later; the day-end
# flush is exact because the last sample's split lands before the rollover).
_integrators: dict = {}
_hc_wh: dict = {}
_last_report: dict = {}


def enabled() -> bool:
    return ENABLED


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
    if not ENABLED:
        logger.info("Power sensors disabled (set MQTT_HOST + POWER_SENSORS to enable)")
        return None
    listeners = []
    for s in SENSORS:
        listener = PowerMqttListener(
            s.slug, MQTT_HOST, MQTT_PORT, s.topic, MQTT_USERNAME, MQTT_PASSWORD,
            _make_on_power(s.slug),
        )
        listener.start()
        listeners.append(listener)
        logger.info("Power MQTT listener started (%s) on %s:%d (%s)",
                    s.slug, MQTT_HOST, MQTT_PORT, s.topic)
    return listeners


def _merged_by_date(slugs: list, start: str, end: str) -> dict:
    """Sum each day's kWh across all of a group's topics over [start, end).

    A day present for at least one member appears in the result (sum of the
    present members); a day absent from every member is simply missing, so the
    caller's `.get(day)` yields `None` and the sparkline keeps its gap."""
    merged: dict = {}
    for slug in slugs:
        for r in repository.get_cached_power(slug, start, end):
            merged[r["date"]] = merged.get(r["date"], 0.0) + r["cons_kwh"]
    return merged


def _hc_pct(slugs: list, start: str, end: str):
    """% of the group's [start, end) consumption that fell in off-peak windows.

    Only days whose hc_wh is known (non-NULL) count — numerator and denominator
    stay on the same day set, so pre-deployment history (no HC split) is simply
    excluded. None when no day has HC info yet, or nothing was consumed."""
    cons_sum = 0.0
    hc_sum = 0.0
    have_hc = False
    for slug in slugs:
        for r in repository.get_cached_power(slug, start, end):
            if r["hc_kwh"] is None:
                continue
            have_hc = True
            cons_sum += r["cons_kwh"]
            hc_sum += r["hc_kwh"]
    if not have_hc or cons_sum <= 0:
        return None
    return round(hc_sum / cons_sum * 100)


def _group_spark(slugs: list, today, today_str: str) -> list:
    """The last 7 complete days' summed kWh (oldest→newest, ending yesterday),
    aligned with the EDF chart axis. `None` for any day no member reported."""
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    by_date = _merged_by_date(slugs, week_ago, today_str)
    return [by_date.get((today - timedelta(days=n)).strftime("%Y-%m-%d")) for n in range(7, 0, -1)]


def _group_stats(slugs: list, today, today_str: str) -> dict:
    """Yesterday's kWh, recent daily average and trend for one group (summed).

    Unlike the Linky data (whose API can return garbage), a plug's reading is
    trusted as-is — every recorded day counts toward the average (no near-zero
    floor), and small values render in Wh rather than collapsing to "0.0 kWh"."""
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    # None = no report at all yesterday (listener down, pre-install) — distinct
    # from a real 0 Wh day (device off but reporting), which renders "0 Wh".
    yesterday_kwh = _merged_by_date(slugs, yesterday_str, today_str).get(yesterday_str)

    past = list(_merged_by_date(slugs, nine_ago, today_str).values())
    avg = sum(past) / len(past) if past else 0.0

    # Trend: last 9 days vs the 28 days before them (mirrors the solar stats).
    prev_start = (today - timedelta(days=37)).strftime("%Y-%m-%d")
    prev = list(_merged_by_date(slugs, prev_start, nine_ago).values())
    avg_prev = sum(prev) / len(prev) if prev else 0.0
    trend_pct = round((avg - avg_prev) / avg_prev * 100) if avg_prev > 0 else 0

    # "—" with the unit kept = the figure exists but isn't initialised yet.
    yesterday_text, yesterday_unit = (
        format_energy_kwh(yesterday_kwh, "") if yesterday_kwh is not None else ("—", "kWh"))
    avg_text, avg_unit = format_energy_kwh(avg, "/j") if past else ("—", "kWh/j")
    return {
        "yesterday_text": yesterday_text,
        "yesterday_unit": yesterday_unit,
        "avg_text": avg_text,
        "avg_unit": avg_unit,
        "avg_kwh": avg if past else None,  # numeric (kWh) for sorting + alert money
        "trend_pct": trend_pct,
        "hc_pct": _hc_pct(slugs, nine_ago, today_str),  # int 0..100 or None (no HC info yet)
        # Prior-period HC share (same window as the trend) for the alert that
        # spots a plug drifting out of the off-peak hours.
        "hc_pct_prev": _hc_pct(slugs, prev_start, nine_ago),
        "spark": _group_spark(slugs, today, today_str),
    }


def attach(data: dict):
    """Attach one bottom-table entry per group (label) — topics sharing a label
    are summed (yesterday kWh + recent average).

    Integrated from each device's reported power (no energy counter); history
    starts at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    data["power_sensors"] = [
        {"name": name, **_group_stats(slugs, today, today_str)}
        for name, slugs in _groups(SENSORS)
    ]


def status() -> dict:
    return {"power_enabled": ENABLED, "last_power": dict(_last_report)}
