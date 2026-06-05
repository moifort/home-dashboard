"""ZLinky_TIC (Lixee) MQTT transport: reads the Linky teleinfo from zigbee2mqtt.

The ZLinky pushes the TIC stream spontaneously (several frames per minute in
mode historique), so — like the water meter — there is nothing to re-request;
we just listen. Payload keys are the uppercase TIC labels: HCHC/HCHP (the
cumulative off-peak/peak indexes), PAPP (apparent power, VA), PTEC (current
pricing period, "HC.."/"HP..").
"""
import json
import logging
import threading

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# A household's lifetime index in kWh stays well under 100k, while the same
# index in Wh is in the millions — the threshold sits safely between the two
# regimes, so the parser is correct whether the Z2M lixee converter publishes
# Wh (its historical behaviour) or kWh.
_WH_THRESHOLD = 100_000


def _to_kwh(raw: float) -> float:
    """Normalize a HCHC/HCHP index to kWh regardless of Wh/kWh source unit."""
    return raw / 1000 if raw >= _WH_THRESHOLD else raw


def _parse_tic(payload: bytes) -> dict | None:
    """Extract the indexes (kWh), PAPP (VA) and tariff period from a Z2M message.

    Returns {"hchc_kwh", "hchp_kwh", "papp_va", "period"} or None when the
    indexes are missing/non-numeric. PAPP may be absent from a frame → None
    (the talon slot just skips it). period is "HC"/"HP" from PTEC, else None.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    hchc = data.get("HCHC")
    hchp = data.get("HCHP")
    if not isinstance(hchc, (int, float)) or not isinstance(hchp, (int, float)):
        return None
    papp = data.get("PAPP")
    ptec = data.get("PTEC")
    period = None
    if isinstance(ptec, str):
        if ptec.startswith("HC"):
            period = "HC"
        elif ptec.startswith("HP"):
            period = "HP"
    return {
        "hchc_kwh": _to_kwh(float(hchc)),
        "hchp_kwh": _to_kwh(float(hchp)),
        "papp_va": float(papp) if isinstance(papp, (int, float)) else None,
        "period": period,
    }


class ZLinkyMqttListener:
    """Background thread reading the Linky teleinfo from an MQTT topic.

    Calls on_tic(reading) for each parsed frame. Reconnects automatically.
    """

    def __init__(self, host, port, topic, username, password, on_tic):
        self._host = host
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._on_tic = on_tic
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="linky-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:
                logger.warning("Linky MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self._username:
            client.username_pw_set(self._username, self._password)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("Linky MQTT connect failed: %s", reason_code)
                return
            c.subscribe(self._topic, qos=0)
            logger.info("Linky MQTT connected, subscribed to %s", self._topic)

        def on_message(c, userdata, msg):
            reading = _parse_tic(msg.payload)
            if reading is not None:
                try:
                    self._on_tic(reading)
                except Exception:
                    logger.exception("on_tic callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(self._host, self._port, keepalive=30)

        while not self._stop.is_set():
            client.loop(timeout=1.0)
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
