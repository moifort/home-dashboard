"""EcoFlow private app API + protobuf heartbeat decoding.

Auth flow and heartbeat parsing mirror tolwi/hassio-ecoflow-cloud. The transport
(MQTT) lives in the mqtt/ subpackage; this module only speaks HTTP + protobuf.
"""
import base64
import logging
import time

import requests

from .proto import powerstream_pb2

logger = logging.getLogger(__name__)

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
