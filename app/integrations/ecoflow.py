"""EcoFlow private app API client — reads PowerStream PV power via MQTT.

The PowerStream broadcasts an inverter heartbeat (cmd_func=20/cmd_id=1) with
the instantaneous PV input power, but only while a client actively requests the
quota — so we re-publish a get-quota request periodically to keep it talking.
The reported power is integrated over time into daily kWh totals by the caller.
Auth + MQTT flow mirror the Home Assistant integration tolwi/hassio-ecoflow-cloud.
"""
import base64
import logging
import os
import secrets
import ssl
import threading
import time
from datetime import datetime, timedelta

import certifi
import paho.mqtt.client as mqtt
import requests

from app import db
from app.config import DAYS_FR, PARIS_TZ
from .proto import powerstream_pb2

logger = logging.getLogger(__name__)

EMAIL = os.environ.get("ECOFLOW_EMAIL", "")
PASSWORD = os.environ.get("ECOFLOW_PASSWORD", "")
DEVICE_SN = os.environ.get("ECOFLOW_DEVICE_SN", "")
API_HOST = os.environ.get("ECOFLOW_API_HOST", "api-e.ecoflow.com")
# Electricity price used to value the produced solar energy (own copy so the
# slice stays self-contained and removable).
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))

USER_AGENT = "ecoflow-dashboard/1.0 (github.com/thibaut-mottet/dashboard)"

# cmd_func/cmd_id of the inverter heartbeat carrying PV power.
HEARTBEAT_CMD_FUNC = 20
HEARTBEAT_CMD_ID = 1

# AddressId.APP — used as src/dest in the get-quota request.
ADDR_APP = 32
# Re-send the get-quota request on this cadence (seconds) to keep the device
# broadcasting; without it the PowerStream stops publishing when no app watches.
GET_QUOTA_INTERVAL = 60


class EcoflowApiError(Exception):
    pass


class EcoflowAuthError(EcoflowApiError):
    pass


def login(email: str, password: str, host: str) -> tuple[str, str]:
    """Authenticate against the private app API. Returns (token, user_id)."""
    url = f"https://{host}/auth/login"
    body = {
        "email": email,
        "password": base64.b64encode(password.encode()).decode(),
        "scene": "IOT_APP",
        "userType": "ECOFLOW",
    }
    headers = {"lang": "en_US", "content-type": "application/json", "User-Agent": USER_AGENT}
    resp = requests.post(url, json=body, headers=headers, timeout=30)
    if resp.status_code in (401, 403):
        raise EcoflowAuthError(f"Login rejected: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("message", "")).lower() != "success":
        raise EcoflowAuthError(f"Login failed: {data.get('message')}")
    payload = data["data"]
    return payload["token"], payload["user"]["userId"]


def get_mqtt_certification(token: str, host: str) -> dict:
    """Fetch MQTT broker credentials. Returns dict with url, port, user, password."""
    url = f"https://{host}/iot-auth/app/certification"
    headers = {
        "lang": "en_US",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "User-Agent": USER_AGENT,
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code in (401, 403):
        raise EcoflowAuthError(f"Certification rejected: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()["data"]
    return {
        "url": data["url"],
        "port": int(data["port"]),
        "user": data["certificateAccount"],
        "password": data["certificatePassword"],
    }


def decode_pv_power(payload: bytes) -> float | None:
    """Decode an MQTT payload, returning total PV power in watts if it is a heartbeat.

    PV watts are reported in deci-watts (value / 10). Returns None for other messages.
    """
    packet = powerstream_pb2.PowerStreamSendHeaderMsg()
    try:
        packet.ParseFromString(payload)
    except Exception:
        return None

    for message in packet.msg:
        if message.cmd_func != HEARTBEAT_CMD_FUNC or message.cmd_id != HEARTBEAT_CMD_ID:
            continue
        hb = powerstream_pb2.PowerStreamInverterHeartbeat()
        try:
            hb.ParseFromString(message.pdata)
        except Exception:
            continue
        return (hb.pv1_input_watts + hb.pv2_input_watts) / 10
    return None


def build_get_quota_request(device_sn: str) -> bytes:
    """Build the protobuf "get latest quota" request (cmd_func=20/cmd_id=1).

    Publishing it keeps the device broadcasting its heartbeat. Mirrors
    tolwi/hassio-ecoflow-cloud.
    """
    packet = powerstream_pb2.PowerStreamSendHeaderMsg()
    msg = packet.msg.add()
    msg.src = ADDR_APP
    msg.dest = ADDR_APP
    msg.cmd_func = HEARTBEAT_CMD_FUNC
    msg.cmd_id = HEARTBEAT_CMD_ID
    msg.data_len = 0
    msg.seq = int(time.time())
    msg.device_sn = device_sn
    msg.from_ = "dashboard"
    return packet.SerializeToString()


class EcoflowMqttListener:
    """Background thread keeping an MQTT connection open, decoding PV power.

    On each heartbeat it calls on_power(pv_watts) with the reported total PV
    power. Re-logins and reconnects automatically on failure.
    """

    def __init__(self, email: str, password: str, device_sn: str, host: str, on_power):
        self._email = email
        self._password = password
        self._sn = device_sn
        self._host = host
        self._on_power = on_power
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="ecoflow-mqtt", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except EcoflowAuthError as exc:
                logger.critical("EcoFlow auth error: %s", exc)
                self._stop.wait(300)
            except Exception as exc:
                logger.warning("EcoFlow MQTT session ended (%s), retrying in 60s", exc)
                self._stop.wait(60)

    def _connect_and_listen(self):
        token, user_id = login(self._email, self._password, self._host)
        cert = get_mqtt_certification(token, self._host)
        client_id = f"ANDROID_{secrets.token_hex(16).upper()}_{user_id}"

        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        client.username_pw_set(cert["user"], cert["password"])
        client.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(False)

        topics = [
            f"/app/device/property/{self._sn}",
            f"/app/{user_id}/{self._sn}/thing/property/get",
            f"/app/{user_id}/{self._sn}/thing/property/get_reply",
            f"/app/{user_id}/{self._sn}/thing/property/set",
            f"/app/{user_id}/{self._sn}/thing/property/set_reply",
        ]

        get_topic = f"/app/{user_id}/{self._sn}/thing/property/get"

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("EcoFlow MQTT connect failed: %s", reason_code)
                return
            for t in topics:
                c.subscribe(t, qos=1)
            c.publish(get_topic, build_get_quota_request(self._sn), qos=1)
            logger.info("EcoFlow MQTT connected, subscribed to %d topics", len(topics))

        def on_message(c, userdata, msg):
            pv_watts = decode_pv_power(msg.payload)
            if pv_watts is not None:
                try:
                    self._on_power(pv_watts)
                except Exception:
                    logger.exception("on_power callback failed")

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.connect(cert["url"], cert["port"], keepalive=15)

        last_poll = time.monotonic()
        while not self._stop.is_set():
            client.loop(timeout=1.0)
            if time.monotonic() - last_poll >= GET_QUOTA_INTERVAL:
                client.publish(get_topic, build_get_quota_request(self._sn), qos=1)
                last_poll = time.monotonic()
        client.disconnect()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


# --- Slice orchestration: enable, integrate power -> daily kWh, panel, status ---

ENABLED = bool(EMAIL and PASSWORD and DEVICE_SN)

# Integration state for reported PV power -> daily kWh. Only the MQTT listener
# thread touches it, so no lock is needed.
_solar_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PERSIST_INTERVAL = 30  # seconds between SQLite writes
_last_solar_report = ""


def enabled() -> bool:
    return ENABLED


def init_schema():
    """Create the daily_production table (idempotent)."""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_production (
            date TEXT PRIMARY KEY,
            pv_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _on_solar_power(pv_watts: float):
    """MQTT callback: integrate reported PV power into today's kWh total."""
    global _last_solar_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _solar_state

    if st["date"] != today:
        if st["date"] is not None:
            db.upsert_production(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = db.get_cached_production(today, tomorrow)
        st["date"] = today
        st["wh"] = existing[0]["pv_kwh"] * 1000 if existing else 0.0
        st["last_ts"] = None
        st["last_persist"] = 0.0

    if st["last_ts"] is not None:
        dt_h = (now - st["last_ts"]).total_seconds() / 3600
        if dt_h > 0:
            st["wh"] += pv_watts * min(dt_h, MAX_SAMPLE_GAP_H)
    st["last_ts"] = now

    mono = time.monotonic()
    if mono - st["last_persist"] >= PERSIST_INTERVAL:
        db.upsert_production(today, st["wh"])
        st["last_persist"] = mono
    _last_solar_report = now.isoformat()


def start():
    """Start the EcoFlow MQTT listener if enabled, else log and do nothing."""
    if not ENABLED:
        logger.info("EcoFlow integration disabled (set ECOFLOW_EMAIL/PASSWORD/DEVICE_SN to enable)")
        return None
    listener = EcoflowMqttListener(EMAIL, PASSWORD, DEVICE_SN, API_HOST, _on_solar_power)
    listener.start()
    logger.info("EcoFlow MQTT listener started for SN %s", DEVICE_SN)
    return listener


def attach(data: dict):
    """Add the solar production history: always the last 9 completed days.

    Days without accumulated data show as N/A. Today is excluded (only complete
    days, whose total we are sure was fully accumulated).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    full_start = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    prod_by_date = {p["date"]: p["pv_kwh"]
                    for p in db.get_cached_production(full_start, today.strftime("%Y-%m-%d"))}

    production_days = []
    recent = []
    for i in range(9, 0, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        pv = prod_by_date.get(ds, 0.0)
        production_days.append({"day": DAYS_FR[d.weekday()], "date": ds, "pv_kwh": pv})
        recent.append({"pv_kwh": pv})

    previous = [{"pv_kwh": prod_by_date[ds]}
                for i in range(37, 9, -1)
                if (ds := (today - timedelta(days=i)).strftime("%Y-%m-%d")) in prod_by_date]

    data["production_days"] = production_days
    data["production_stats"] = _compute_production_stats(recent, previous)


def _compute_production_stats(current: list[dict], previous: list[dict]) -> dict:
    na_threshold = 0.1

    def _avg(days):
        valid = [d for d in days if d["pv_kwh"] >= na_threshold]
        if not valid:
            return 0
        return sum(d["pv_kwh"] for d in valid) / len(valid)

    avg_kwh = _avg(current)
    avg_kwh_prev = _avg(previous)
    has_prev = avg_kwh_prev > 0

    pct = round((avg_kwh - avg_kwh_prev) / avg_kwh_prev * 100, 1) if has_prev else 0
    total = sum(d["pv_kwh"] for d in current)
    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": pct,
        "total_kwh": round(total, 1),
        "savings_eur": round(total * PRICE_HP, 1),
    }


def status() -> dict:
    return {"ecoflow_enabled": ENABLED, "last_solar_report": _last_solar_report}
