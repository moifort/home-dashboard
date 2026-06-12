"""Unit tests for the shared MQTT network-loop pump (module/mqtt.py).

The zombie-listener bug: paho's manual Client.loop() returns an error code on a
lost connection and never reconnects by itself (auto-reconnect only exists in
loop_forever()/loop_start()). A listener that ignores that code keeps spinning,
subscribed to nothing, until the process restarts. The pump must surface the
lost connection as an exception so each listener's retry loop reconnects.
"""
import threading

import pytest

from app.module.mqtt import pump


class _FakeClient:
    """Stand-in for paho's Client: scripted loop() return codes; the last code
    repeats. Optionally sets `stop` after a number of loop() calls."""

    def __init__(self, rcs, stop=None, stop_after=None):
        self._rcs = list(rcs)
        self.loops = 0
        self.disconnected = False
        self._stop = stop
        self._stop_after = stop_after

    def loop(self, timeout=1.0):
        rc = self._rcs[min(self.loops, len(self._rcs) - 1)]
        self.loops += 1
        if self._stop_after is not None and self.loops >= self._stop_after:
            self._stop.set()
        return rc

    def disconnect(self):
        self.disconnected = True


def test_lost_connection_raises_for_the_retry_loop():
    stop = threading.Event()
    client = _FakeClient([0, 0, 7])  # healthy, healthy, MQTT_ERR_CONN_LOST
    with pytest.raises(ConnectionError):
        pump(client, stop)
    assert client.loops == 3  # raised on the first bad code, not later


def test_clean_stop_disconnects_without_raising():
    stop = threading.Event()
    client = _FakeClient([0], stop=stop, stop_after=3)
    pump(client, stop)
    assert client.disconnected is True
    assert client.loops == 3


def test_tick_runs_each_healthy_iteration():
    # The periodic re-poll hook (power/solar get requests) must keep running.
    stop = threading.Event()
    client = _FakeClient([0], stop=stop, stop_after=2)
    ticks = []
    pump(client, stop, tick=lambda: ticks.append(1))
    assert len(ticks) == 2
