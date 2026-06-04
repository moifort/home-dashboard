"""Screen-refresh schedule — the single source of truth shared by the server loop
and the Home panel.

The ESP32 wakes on a clock-aligned interval (`SCREEN_REFRESH_INTERVAL_MIN`, e.g.
every 2 h at 00:00, 02:00 … 22:00 — see `hardware/esp32-display/esp32-display.ino`) and
pulls `/display`. To serve fresh data the server regenerates the buffer
`DATA_LEAD_MIN` minutes *before* each of those boundaries (so the ESP always picks
up a render that is at most a few minutes old). Both numbers live in `config.py`.

All helpers are pure functions of the `now` they are handed, so the golden tests
can drive them with a frozen clock.
"""
from datetime import datetime, timedelta

from app.system.config import DATA_LEAD_MIN, SCREEN_REFRESH_INTERVAL_MIN, SCREEN_WAKE_SKIP_MIN


def next_screen_refresh(now: datetime) -> datetime:
    """The next clock-aligned screen-refresh boundary strictly after `now`.

    Mirrors the ESP firmware: boundaries fall on minute-of-day multiples of the
    interval (02:00, 04:00 … for 120 min)."""
    base = now.replace(second=0, microsecond=0)
    minute_of_day = base.hour * 60 + base.minute
    rem = SCREEN_REFRESH_INTERVAL_MIN - (minute_of_day % SCREEN_REFRESH_INTERVAL_MIN)
    return base + timedelta(minutes=rem)


def next_screen_wake(now: datetime) -> datetime:
    """The device's next *actual* wake, mirroring the firmware's skip guard.

    Clock drift can wake the ESP a few minutes before a boundary; the firmware
    then skips that boundary (it effectively just refreshed) and sleeps to the
    following one (`sleep_min < SCREEN_WAKE_SKIP_MIN` → += interval in
    computeSleepUs). The Home panel's "next refresh" must reflect that real wake,
    not the raw next boundary — e.g. a pull at 09:59 shows 12:00, not 10:00."""
    base = now.replace(second=0, microsecond=0)
    minute_of_day = base.hour * 60 + base.minute
    sleep_min = SCREEN_REFRESH_INTERVAL_MIN - (minute_of_day % SCREEN_REFRESH_INTERVAL_MIN)
    if sleep_min < SCREEN_WAKE_SKIP_MIN:
        sleep_min += SCREEN_REFRESH_INTERVAL_MIN
    return base + timedelta(minutes=sleep_min)


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
