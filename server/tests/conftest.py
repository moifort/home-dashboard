"""Shared pytest fixtures for the golden tests.

Two sources of non-determinism are neutralised here so the pipeline is a pure
function of seeded data:
  * **time** — every module reads `datetime.now(PARIS_TZ)`; `frozen_now` swaps the
    `datetime` symbol in each for a subclass pinned to `seed_db.FIXED_NOW`.
  * **storage / network** — `seeded_db` points the DB at a temp file filled by
    `seed_db.seed()`, enables the DB-backed slices, and hard-disables the
    network slices (crypto, UniFi) so `build_dashboard_data` never reaches out.

`--update-golden` flips the tests from *assert* to *write* mode (re-baselining).
"""
from datetime import datetime
from pathlib import Path

import pytest

from app.module import db
from app.integrations import crypto, ecoflow, power, unifi, water
from app.integrations.power import Sensor
from tests.fixtures import seed_db
from tests.fixtures.seed_db import FIXED_NOW

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Modules that call datetime.now(PARIS_TZ) on the build/render path. Each does
# `from datetime import datetime`, so the name lives in the module namespace.
_TIME_MODULES = [
    "app.dashboard_data",
    "app.module.db",
    "app.integrations.linky",
    "app.solar.query",
    "app.solar.command",
    "app.integrations.power",
    "app.water.query",
]


class _FrozenDateTime(datetime):
    """datetime whose now() is pinned; strptime/fromisoformat stay inherited."""

    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="Regenerate the committed golden references instead of asserting.",
    )


@pytest.fixture
def update_golden(request) -> bool:
    return request.config.getoption("--update-golden")


@pytest.fixture
def frozen_now(monkeypatch):
    """Freeze datetime.now() across the whole build/render path."""
    for mod in _TIME_MODULES:
        monkeypatch.setattr(mod + ".datetime", _FrozenDateTime)
    return FIXED_NOW


@pytest.fixture
def seeded_db(tmp_path, monkeypatch, frozen_now):
    """A temp SQLite seeded deterministically, with the DB-backed slices enabled
    and the network slices disabled."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))

    # Enable the slices the seeded tables back; give water a €/m³ so its cost +
    # the water_drop money path are exercised.
    monkeypatch.setattr(ecoflow, "ENABLED", True)
    monkeypatch.setattr(power, "SENSORS", [
        Sensor("cumulus", "zigbee2mqtt/cumulus", "Cumulus"),
        Sensor("lave-linge", "zigbee2mqtt/lave-linge", "Lave-linge"),
        # Two topics sharing the "Salon" label -> one summed bottom-table row.
        Sensor(seed_db.SALON_1_SLUG, "zigbee2mqtt/prise-1", "Salon"),
        Sensor(seed_db.SALON_2_SLUG, "zigbee2mqtt/prise-2", "Salon"),
    ])
    monkeypatch.setattr(power, "ENABLED", True)
    monkeypatch.setattr(water, "ENABLED", True)
    monkeypatch.setattr(water, "PRICE_M3", 3.9)

    # Hard-disable the network slices so build_dashboard_data never fetches.
    monkeypatch.setattr(crypto, "enabled", lambda: False)
    monkeypatch.setattr(unifi, "enabled", lambda: False)

    seed_db.seed()
    return db_file
