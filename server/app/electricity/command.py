"""Electricity domain commands (write side): schema init + Conso API fetch/cache."""
import logging
from datetime import datetime, timedelta

from app.system.config import PARIS_TZ
from app.electricity.infrastructure import repository
from app.electricity.infrastructure.linky_api import fetch_load_curve
from app.electricity.infrastructure.linky_client import (
    LinkyApiError,
    LinkyAuthError,
    compute_daily_hc_hp,
)

logger = logging.getLogger(__name__)

# Runtime state surfaced by query.status().
last_fetch_time = ""
last_error = ""


def init_schema():
    """Create the daily_consumption table (idempotent) + talon migrations."""
    repository.init_schema()


def fetch_and_cache() -> list[dict]:
    """Fetch missing/stale daily HC/HP from the Conso API and return 35 days."""
    global last_fetch_time, last_error
    from app.electricity import HC_WINDOWS, PRM, TOKEN

    now = datetime.now(PARIS_TZ)
    end_date = now.strftime("%Y-%m-%d")
    full_start = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    if not repository.needs_refresh(week_start, end_date):
        logger.info("Cache is fresh, skipping API call")
        return repository.get_cached_days(full_start, end_date)

    for week_offset in range(5):
        chunk_end = now - timedelta(days=week_offset * 7)
        chunk_start = chunk_end - timedelta(days=7)
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        cached = repository.get_cached_days(s, e)
        # Skip cached chunks, but force a one-time backfill of older weeks whose
        # rows predate the talon column (talon_w still NULL).
        if cached and week_offset > 0 and all(d.get("talon_w") is not None for d in cached):
            continue
        logger.info("Fetching load curve: %s to %s", s, e)
        try:
            raw = fetch_load_curve(TOKEN, PRM, s, e)
            days = compute_daily_hc_hp(raw, HC_WINDOWS)
            if days:
                repository.upsert_days(days)
        except LinkyAuthError as exc:
            logger.critical("Auth error: %s", exc)
            last_error = str(exc)
            break
        except LinkyApiError as exc:
            logger.warning("API error for %s-%s: %s", s, e, exc)
            last_error = str(exc)
            continue

    last_fetch_time = now.isoformat()
    if not last_error:
        last_error = ""
    return repository.get_cached_days(full_start, end_date)
