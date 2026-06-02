"""Screen-refresh schedule — the single source of truth shared by the server loop
and the Home panel.

The ESP32 wakes on a clock-aligned interval (`SCREEN_REFRESH_INTERVAL_MIN`, e.g.
every 2 h at 00:00, 02:00 … 22:00 — see `esp32-display/esp32-display.ino`) and
pulls `/display`. To serve fresh data the server regenerates the buffer
`DATA_LEAD_MIN` minutes *before* each of those boundaries (so the ESP always picks
up a render that is at most a few minutes old). Both numbers live in `config.py`.

All helpers are pure functions of the `now` they are handed, so the golden tests
can drive them with a frozen clock.
"""
from datetime import datetime, timedelta

from app.config import DATA_LEAD_MIN, SCREEN_REFRESH_INTERVAL_MIN


def next_screen_refresh(now: datetime) -> datetime:
    """The next clock-aligned screen-refresh boundary strictly after `now`.

    Mirrors the ESP firmware: boundaries fall on minute-of-day multiples of the
    interval (02:00, 04:00 … for 120 min)."""
    base = now.replace(second=0, microsecond=0)
    minute_of_day = base.hour * 60 + base.minute
    rem = SCREEN_REFRESH_INTERVAL_MIN - (minute_of_day % SCREEN_REFRESH_INTERVAL_MIN)
    return base + timedelta(minutes=rem)


def current_screen_refresh(now: datetime) -> datetime:
    """The boundary the image rendered *now* is meant for.

    During the pre-render lead window (within `DATA_LEAD_MIN` of a boundary) it is
    the upcoming boundary; otherwise it is the last boundary that already passed —
    so a re-render mid-window (e.g. the live crypto pull) still reports the screen
    refresh the user is actually looking at."""
    nb = next_screen_refresh(now)
    if nb - now <= timedelta(minutes=DATA_LEAD_MIN):
        return nb
    return nb - timedelta(minutes=SCREEN_REFRESH_INTERVAL_MIN)


def next_data_update(now: datetime) -> datetime:
    """The next moment the server should regenerate data: `DATA_LEAD_MIN` before a
    screen boundary. Skips to the following boundary's lead point if `now` is
    already inside (or past) the current one."""
    nb = next_screen_refresh(now)
    target = nb - timedelta(minutes=DATA_LEAD_MIN)
    if target <= now:
        target = nb + timedelta(minutes=SCREEN_REFRESH_INTERVAL_MIN - DATA_LEAD_MIN)
    return target
