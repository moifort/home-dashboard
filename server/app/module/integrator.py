"""Shared watts → daily-Wh integrator (transverse infrastructure).

Solar (PowerStream heartbeat) and the power sensors (Z2M plugs) both receive
only instantaneous watts and integrate them into a per-day Wh total with the
same state machine: time-weighted increments capped at MAX_SAMPLE_GAP_H (so a
quiet stream never over-counts silence), a day-rollover flush + reload of any
partial row (restart resilience), and SQLite persists throttled to
PERSIST_INTERVAL. This class is that machine; the domains inject their own
persist/reload callbacks.

The integrator NEVER reads the clock itself: `now` is always passed by the
caller (whose module the test suite freezes).
"""
import time

MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30      # seconds between SQLite writes


class DailyEnergyIntegrator:
    """Integrate instantaneous watts into a daily Wh total.

    `flush(date, wh)` persists a day's running total (called at each rollover
    for the finished day and on the PERSIST_INTERVAL throttle for today);
    `reload(date) -> float` returns the day's already-persisted Wh (0.0 if
    none) so a restart resumes instead of resetting.

    Only one MQTT listener thread feeds a given instance, so no lock is needed.
    `feed` returns the increment (Wh) added by this sample so the caller can
    apply its own splits (e.g. the power sensors' off-peak share).
    """

    def __init__(self, flush, reload):
        self._flush = flush
        self._reload = reload
        self.date = None
        self.wh = 0.0
        self._last_ts = None
        self._last_persist = 0.0

    def feed(self, watts: float, now) -> float:
        today = now.strftime("%Y-%m-%d")
        if self.date != today:
            if self.date is not None:
                self._flush(self.date, self.wh)  # flush the finished day
            self.date = today
            self.wh = self._reload(today)
            self._last_ts = None
            self._last_persist = 0.0

        inc = 0.0
        if self._last_ts is not None:
            dt_h = (now - self._last_ts).total_seconds() / 3600
            if dt_h > 0:
                inc = watts * min(dt_h, MAX_SAMPLE_GAP_H)
                self.wh += inc
        self._last_ts = now

        mono = time.monotonic()
        if mono - self._last_persist >= PERSIST_INTERVAL:
            self._flush(today, self.wh)
            self._last_persist = mono
        return inc
