"""Shared 30-min slot helpers (transverse infrastructure).

Every *_samples table (tic_samples, solar_samples, water_samples) buckets its
history in half-hour slots keyed by the slot's ISO local start; the intraday
profile readers index a 48-entry day scaffold the same way. These helpers are
the single definition of that convention.
"""
from datetime import datetime

SLOT_MIN = 30           # slot width (minutes) — 48 slots per day
SLOTS_PER_DAY = 48


def slot_start(now: datetime) -> str:
    """The ISO start of `now`'s 30-min slot (local time)."""
    return now.replace(minute=now.minute - now.minute % SLOT_MIN,
                       second=0, microsecond=0).isoformat()


def slot_index(dt: datetime) -> int:
    """The 0..47 index of `dt`'s 30-min slot within its day."""
    return dt.hour * 2 + (1 if dt.minute >= 30 else 0)
