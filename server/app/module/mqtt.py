"""Shared MQTT network-loop pump (transverse infrastructure).

paho's manual Client.loop() does NOT reconnect by itself: on a lost connection
it just returns an error code, forever — auto-reconnect only exists inside
loop_forever()/loop_start(), which the listeners don't use. A listener that
ignores that code keeps spinning, subscribed to nothing, until the process
restarts (and burns CPU: loop() returns immediately on a dead socket). pump()
surfaces the failure as ConnectionError so each listener's existing retry loop
reconnects with a fresh connect + resubscribe.
"""
import paho.mqtt.client as mqtt


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
