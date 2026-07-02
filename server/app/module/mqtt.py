"""Shared MQTT listener infrastructure (transverse).

paho's manual Client.loop() does NOT reconnect by itself: on a lost connection
it just returns an error code, forever — auto-reconnect only exists inside
loop_forever()/loop_start(), which the listeners don't use. A listener that
ignores that code keeps spinning, subscribed to nothing, until the process
restarts (and burns CPU: loop() returns immediately on a dead socket). pump()
surfaces the failure as ConnectionError so each listener's retry loop
reconnects with a fresh connect + resubscribe.

MqttListener is the common subscribe-and-parse skeleton every plain-broker
domain listener shares (linky, water, plants, power): a daemon thread running
a 60s-retry loop around connect → subscribe → parse each message → guarded
callback → pump. Subclasses supply the parse function and may hook the
subscribe moment (`_on_subscribed`) and a periodic re-poll (`_tick`). The
EcoFlow listener stays separate — TLS, login and protobuf make it a genuinely
different shape.
"""
import logging
import threading

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


def pump(client, stop, tick=None):
    """Drive a connected client's network loop until `stop` is set, then
    disconnect. `tick()` runs after each healthy iteration (periodic re-polls).
    Raises ConnectionError as soon as the network loop reports a failure."""
    while not stop.is_set():
        rc = client.loop(timeout=1.0)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT network loop failed (rc={rc})")
        if tick is not None:
            tick()
    client.disconnect()


class MqttListener:
    """Background thread reading one MQTT topic and feeding parsed values to a
    callback. Reconnects automatically (fresh connect + resubscribe every 60s
    after a lost session).

    Subclasses must implement `_parse(payload) -> value | None` (None = skip)
    and may override `_on_subscribed(client)` (extra publish at subscribe time)
    and `_tick(client)` (runs after each healthy network-loop iteration).
    """

    def __init__(self, host, port, topic, username, password, callback,
                 *, label, thread_name):
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._callback = callback
        self._label = label
        self._thread_name = thread_name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _parse(self, payload: bytes):
        raise NotImplementedError

    def _on_subscribed(self, client):
        """Hook: extra work at subscribe time (e.g. an initial `/get` publish)."""

    def _tick(self, client):
        """Hook: periodic work per healthy loop iteration (e.g. a re-poll)."""

    def start(self):
        self._thread = threading.Thread(target=self._run, name=self._thread_name,
                                        daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning("%s MQTT session ended (%s), retrying in 60s",
                               self._label, exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("%s MQTT connect failed: %s", self._label, reason_code)
                return
            c.subscribe(self._topic, qos=0)
            self._on_subscribed(c)
            logger.info("%s MQTT connected, subscribed to %s", self._label, self._topic)

        def on_message(c, userdata, msg):
            value = self._parse(msg.payload)
            if value is not None:
                try:
                    self._callback(value)
                except Exception:
                    logger.exception("%s MQTT callback failed", self._label)

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(self._host, self._port, keepalive=30)
        pump(client, self._stop, tick=lambda: self._tick(client))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
