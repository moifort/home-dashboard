"""Layer 1 — data pipeline golden.

Seeded DB + frozen time → build_dashboard_data() → compared to data.golden.json.
Covers the orchestrator (app.dashboard_data), the DB-backed integrations (Linky
core, solar, cumulus, water) and the alerts engine. No font rendering here, so
this golden is fully portable (byte-exact on macOS and the Linux CI alike).
"""
import difflib
from datetime import timedelta

from app.dashboard_data import build_dashboard_data
from app.electricity.infrastructure import repository
from app.system.tests._golden import canonical_json
from app.system.tests.conftest import FIXTURES_DIR
from app.system.tests.fixtures.seed_db import TODAY

GOLDEN = FIXTURES_DIR / "data.golden.json"


def _read_all_days():
    start = (TODAY - timedelta(days=60)).strftime("%Y-%m-%d")
    end = (TODAY + timedelta(days=1)).strftime("%Y-%m-%d")
    return repository.get_cached_days(start, end)


def test_data_pipeline_golden(seeded_db, update_golden):
    data = build_dashboard_data(_read_all_days())
    actual = canonical_json(data)

    if update_golden:
        GOLDEN.write_text(actual, encoding="utf-8")
        return

    assert GOLDEN.exists(), "Run `pytest --update-golden` once to create the baseline."
    expected = GOLDEN.read_text(encoding="utf-8")
    if actual != expected:
        diff = "\n".join(difflib.unified_diff(
            expected.splitlines(), actual.splitlines(),
            fromfile="data.golden.json", tofile="actual", lineterm="",
        ))
        raise AssertionError("Data pipeline output changed:\n" + diff)
