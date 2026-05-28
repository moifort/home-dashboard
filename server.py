#!/usr/bin/env python3
"""Linky dashboard server for CasaOS — fetches electricity data and serves EPD buffer."""
import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from converter import png_to_epd_buffer
from crypto_client import build_crypto_panel, fetch_crypto_stats
from cumulus_client import CumulusMqttListener
from ecoflow_client import EcoflowMqttListener
from linky_client import (
    LinkyApiError,
    LinkyAuthError,
    compute_daily_hc_hp,
    fetch_load_curve,
    parse_hc_windows,
)
from renderer import render_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent

PARIS_TZ = ZoneInfo("Europe/Paris")
DAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

TOKEN = os.environ.get("LINKY_TOKEN", "")
PRM = os.environ.get("LINKY_PRM", "")
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "3600"))
HC_WINDOWS = parse_hc_windows(os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02"))
PRICE_HP = float(os.environ.get("PRICE_HP", "0.2065"))
PRICE_HC = float(os.environ.get("PRICE_HC", "0.1579"))
PRICE_ABO_MONTHLY = float(os.environ.get("PRICE_ABO_MONTHLY", "15.65"))
RENDER_MODE = os.environ.get("RENDER_MODE", "4color")
DB_PATH = os.environ.get("DB_PATH", "/data/linky.db")
PORT = int(os.environ.get("PORT", "5000"))
SAVE_PNG = os.environ.get("SAVE_PNG", "false").lower() == "true"

ECOFLOW_EMAIL = os.environ.get("ECOFLOW_EMAIL", "")
ECOFLOW_PASSWORD = os.environ.get("ECOFLOW_PASSWORD", "")
ECOFLOW_DEVICE_SN = os.environ.get("ECOFLOW_DEVICE_SN", "")
ECOFLOW_API_HOST = os.environ.get("ECOFLOW_API_HOST", "api-e.ecoflow.com")
ECOFLOW_ENABLED = bool(ECOFLOW_EMAIL and ECOFLOW_PASSWORD and ECOFLOW_DEVICE_SN)

CRYPTO_API_URL = os.environ.get("CRYPTO_API_URL", "")
CRYPTO_API_TOKEN = os.environ.get("CRYPTO_API_TOKEN", "")
CRYPTO_ENABLED = bool(CRYPTO_API_URL)

CUMULUS_MQTT_HOST = os.environ.get("CUMULUS_MQTT_HOST", "")
CUMULUS_MQTT_PORT = int(os.environ.get("CUMULUS_MQTT_PORT", "1883"))
CUMULUS_TOPIC = os.environ.get("CUMULUS_TOPIC", "zigbee2mqtt/cumulus")
CUMULUS_MQTT_USERNAME = os.environ.get("CUMULUS_MQTT_USERNAME", "")
CUMULUS_MQTT_PASSWORD = os.environ.get("CUMULUS_MQTT_PASSWORD", "")
CUMULUS_ENABLED = bool(CUMULUS_MQTT_HOST)

epd_buffer: bytes = b""
buffer_lock = threading.Lock()
dashboard_data: dict = {}
data_lock = threading.Lock()
last_fetch_time: str = ""
last_render_time: str = ""
last_error: str = ""
last_solar_report: str = ""
last_crypto_time: str = ""
last_cumulus_report: str = ""


def get_version() -> str:
    version_file = ROOT / ".version"
    if version_file.exists():
        return version_file.read_text().strip()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


VERSION = get_version()


# --- SQLite Cache ---

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_consumption (
            date TEXT PRIMARY KEY,
            hc_kwh REAL NOT NULL,
            hp_kwh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_production (
            date TEXT PRIMARY KEY,
            pv_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_cumulus (
            date TEXT PRIMARY KEY,
            cons_wh REAL NOT NULL,
            fetched_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def get_cached_cumulus(start: str, end: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT date, cons_wh FROM daily_cumulus WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "cons_kwh": round(r[1] / 1000, 2)} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_cumulus(date: str, cons_wh: float):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO daily_cumulus (date, cons_wh, fetched_at) VALUES (?, ?, ?)",
        (date, cons_wh, now),
    )
    conn.commit()
    conn.close()


def get_cached_production(start: str, end: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT date, pv_wh FROM daily_production WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "pv_kwh": round(r[1] / 1000, 2)} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_production(date: str, pv_wh: float):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO daily_production (date, pv_wh, fetched_at) VALUES (?, ?, ?)",
        (date, pv_wh, now),
    )
    conn.commit()
    conn.close()


# Integration state for reported PV power → daily kWh. Only the MQTT listener
# thread touches it, so no lock is needed.
_solar_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}
MAX_SAMPLE_GAP_H = 5 / 60  # cap a sample's time weight at 5 min to avoid overcounting silence
PRODUCTION_PERSIST_INTERVAL = 30  # seconds between SQLite writes


def _on_solar_power(pv_watts: float):
    """MQTT callback: integrate reported PV power into today's kWh total."""
    global last_solar_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _solar_state

    if st["date"] != today:
        if st["date"] is not None:
            upsert_production(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = get_cached_production(today, tomorrow)
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
    if mono - st["last_persist"] >= PRODUCTION_PERSIST_INTERVAL:
        upsert_production(today, st["wh"])
        st["last_persist"] = mono
    last_solar_report = now.isoformat()


def start_ecoflow_listener() -> EcoflowMqttListener:
    listener = EcoflowMqttListener(
        ECOFLOW_EMAIL, ECOFLOW_PASSWORD, ECOFLOW_DEVICE_SN, ECOFLOW_API_HOST, _on_solar_power
    )
    listener.start()
    logger.info("EcoFlow MQTT listener started for SN %s", ECOFLOW_DEVICE_SN)
    return listener


# Integration state for the cumulus contactor power → daily kWh. Only the MQTT
# listener thread touches it, so no lock is needed. The contactor has no energy
# counter, so we integrate its reported instantaneous power ourselves.
_cumulus_state = {"date": None, "wh": 0.0, "last_ts": None, "last_persist": 0.0}


def _on_cumulus_power(watts: float):
    """MQTT callback: integrate reported cumulus power into today's kWh total."""
    global last_cumulus_report
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    st = _cumulus_state

    if st["date"] != today:
        if st["date"] is not None:
            upsert_cumulus(st["date"], st["wh"])  # flush the finished day
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        existing = get_cached_cumulus(today, tomorrow)
        st["date"] = today
        st["wh"] = existing[0]["cons_kwh"] * 1000 if existing else 0.0
        st["last_ts"] = None
        st["last_persist"] = 0.0

    if st["last_ts"] is not None:
        dt_h = (now - st["last_ts"]).total_seconds() / 3600
        if dt_h > 0:
            st["wh"] += watts * min(dt_h, MAX_SAMPLE_GAP_H)
    st["last_ts"] = now

    mono = time.monotonic()
    if mono - st["last_persist"] >= PRODUCTION_PERSIST_INTERVAL:
        upsert_cumulus(today, st["wh"])
        st["last_persist"] = mono
    last_cumulus_report = now.isoformat()


def start_cumulus_listener() -> CumulusMqttListener:
    listener = CumulusMqttListener(
        CUMULUS_MQTT_HOST, CUMULUS_MQTT_PORT, CUMULUS_TOPIC,
        CUMULUS_MQTT_USERNAME, CUMULUS_MQTT_PASSWORD, _on_cumulus_power,
    )
    listener.start()
    logger.info("Cumulus MQTT listener started on %s:%d (%s)",
                CUMULUS_MQTT_HOST, CUMULUS_MQTT_PORT, CUMULUS_TOPIC)
    return listener


def get_cached_days(start: str, end: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT date, hc_kwh, hp_kwh FROM daily_consumption WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    rows = [{"date": r[0], "hc_kwh": r[1], "hp_kwh": r[2]} for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_days(days: list[dict]):
    now = datetime.now(PARIS_TZ).isoformat()
    conn = sqlite3.connect(DB_PATH)
    for d in days:
        conn.execute(
            "INSERT OR REPLACE INTO daily_consumption (date, hc_kwh, hp_kwh, fetched_at) VALUES (?, ?, ?, ?)",
            (d["date"], d["hc_kwh"], d["hp_kwh"], now),
        )
    conn.commit()
    conn.close()


def needs_refresh(start: str, end: str) -> bool:
    cached = get_cached_days(start, end)
    cached_dates = {d["date"] for d in cached}
    now = datetime.now(PARIS_TZ)

    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current < end_dt:
        ds = current.strftime("%Y-%m-%d")
        if ds not in cached_dates:
            return True
        current += timedelta(days=1)

    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if yesterday in cached_dates:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT fetched_at FROM daily_consumption WHERE date = ?", (yesterday,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            fetched = datetime.fromisoformat(row[0])
            if fetched.astimezone(PARIS_TZ).date() < now.date():
                return True
            if fetched.astimezone(PARIS_TZ).hour < 10:
                return True

    return False


# --- Data Fetching ---

def fetch_and_cache() -> list[dict]:
    global last_fetch_time, last_error
    now = datetime.now(PARIS_TZ)
    end_date = now.strftime("%Y-%m-%d")
    full_start = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    if not needs_refresh(week_start, end_date):
        logger.info("Cache is fresh, skipping API call")
        return get_cached_days(full_start, end_date)

    for week_offset in range(5):
        chunk_end = now - timedelta(days=week_offset * 7)
        chunk_start = chunk_end - timedelta(days=7)
        s = chunk_start.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        if get_cached_days(s, e) and week_offset > 0:
            continue
        logger.info("Fetching load curve: %s to %s", s, e)
        try:
            raw = fetch_load_curve(TOKEN, PRM, s, e)
            days = compute_daily_hc_hp(raw, HC_WINDOWS)
            if days:
                upsert_days(days)
        except LinkyAuthError as exc:
            logger.critical("Auth error: %s", exc)
            last_error = str(exc)
            break
        except LinkyApiError as exc:
            logger.warning("API error for %s-%s: %s", s, e, exc)
            last_error = str(exc)
            continue

    last_fetch_time = now.isoformat()
    if not last_error:
        last_error = ""
    return get_cached_days(full_start, end_date)


def build_dashboard_data(days: list[dict]) -> dict:
    now = datetime.now(PARIS_TZ)
    today = now.strftime("%Y-%m-%d")
    complete_days = [d for d in days if d["date"] < today]

    current_week = complete_days[-9:]
    prev_weeks = complete_days[-37:-9]

    result = []
    for d in current_week:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        day_name = DAYS_FR[dt.weekday()]
        result.append({
            "day": day_name,
            "date": d["date"],
            "hc_kwh": d["hc_kwh"],
            "hp_kwh": d["hp_kwh"],
        })

    stats = _compute_stats(current_week, prev_weeks)
    data = {"days": result, "stats": stats, "last_updated": now.isoformat()}

    if ECOFLOW_ENABLED:
        _attach_production(data)

    if CRYPTO_ENABLED:
        _attach_crypto(data)

    if CUMULUS_ENABLED:
        _attach_cumulus(data)

    return data


CUMULUS_NA_THRESHOLD_KWH = 0.05


def _attach_cumulus(data: dict):
    """Attach the cumulus banner fields: today's kWh and the recent daily average.

    Integrated from the contactor's reported power (no energy counter); history
    starts at first connection (no backfill).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    nine_ago = (today - timedelta(days=9)).strftime("%Y-%m-%d")

    today_rows = get_cached_cumulus(today_str, tomorrow)
    today_kwh = today_rows[0]["cons_kwh"] if today_rows else 0.0

    past = [r["cons_kwh"] for r in get_cached_cumulus(nine_ago, today_str)
            if r["cons_kwh"] >= CUMULUS_NA_THRESHOLD_KWH]
    avg = sum(past) / len(past) if past else 0.0

    data["cumulus"] = {
        "today_text": f"{today_kwh:.1f}",
        "avg_text": f"{avg:.1f}" if past else "N/A",
    }


def _attach_crypto(data: dict):
    """Fetch crypto-bot stats and attach the rendered panel fields.

    On any failure the key is left unset, so the panel is simply omitted.
    """
    global last_crypto_time
    stats = fetch_crypto_stats(CRYPTO_API_URL, CRYPTO_API_TOKEN)
    if not stats:
        return
    data["crypto"] = build_crypto_panel(stats)
    last_crypto_time = datetime.now(PARIS_TZ).isoformat()


def _attach_production(data: dict):
    """Add the solar production history: always the last 9 completed days.

    Days without accumulated data show as N/A. Today is excluded (only complete
    days, whose total we are sure was fully accumulated).
    """
    now = datetime.now(PARIS_TZ)
    today = now.date()
    full_start = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    prod_by_date = {p["date"]: p["pv_kwh"] for p in get_cached_production(full_start, today.strftime("%Y-%m-%d"))}

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
    }


def _compute_stats(current: list[dict], previous: list[dict]) -> dict:
    daily_abo = PRICE_ABO_MONTHLY / 30.44
    na_threshold = 1.0

    def _filter_valid(days):
        return [d for d in days if d["hc_kwh"] + d["hp_kwh"] >= na_threshold]

    def _avg_and_ratios(days):
        if not days:
            return 0, 0, 0
        total_hc = sum(d["hc_kwh"] for d in days)
        total_hp = sum(d["hp_kwh"] for d in days)
        total = total_hc + total_hp
        n = len(days)
        avg_kwh = total / n
        hc_ratio = (total_hc / total * 100) if total > 0 else 0
        avg_price = ((total_hp * PRICE_HP + total_hc * PRICE_HC) / n) + daily_abo
        return avg_kwh, hc_ratio, avg_price

    avg_kwh, hc_ratio, avg_price = _avg_and_ratios(_filter_valid(current))
    has_prev = len(previous) > 0
    avg_kwh_prev, hc_ratio_prev, avg_price_prev = _avg_and_ratios(_filter_valid(previous))

    def _pct(cur, prev):
        if not has_prev or prev == 0:
            return 0
        return round((cur - prev) / prev * 100, 1)

    return {
        "avg_kwh": round(avg_kwh, 1),
        "avg_kwh_pct": _pct(avg_kwh, avg_kwh_prev),
        "hc_ratio": round(hc_ratio, 1),
        "hc_ratio_pct": round(hc_ratio - hc_ratio_prev, 1) if has_prev else 0,
        "avg_price": round(avg_price, 2),
        "avg_price_pct": _pct(avg_price, avg_price_prev),
    }


# --- Rendering (Pillow) ---

def render_to_buffer(data: dict | None = None) -> bytes:
    global last_render_time
    if data is None:
        with data_lock:
            data = dashboard_data

    img = render_dashboard(data)

    if SAVE_PNG:
        out = Path(DB_PATH).parent / "last_render.png"
        img.save(str(out))
        logger.info("Saved render to %s", out)

    buf_io = BytesIO()
    img.save(buf_io, format="PNG")
    buf = png_to_epd_buffer(buf_io.getvalue(), mode=RENDER_MODE)
    last_render_time = datetime.now(PARIS_TZ).isoformat()
    logger.info("Rendered EPD buffer: %d bytes", len(buf))
    return buf


# --- HTTP Server ---

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/display":
            self._serve_display()
        elif self.path == "/status":
            self._serve_status()
        elif self.path == "/api/data":
            self._serve_data()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/refresh":
            self._handle_refresh()
        else:
            self.send_error(404)

    def _fresh_or_cached_buffer(self) -> bytes:
        """Buffer for /display: re-render with fresh crypto on the ESP32's pull.

        Linky/solar data stay on the hourly cache; only the crypto panel is
        refreshed here. Any failure falls back to the cached hourly buffer.
        """
        if CRYPTO_ENABLED:
            try:
                with data_lock:
                    data = dict(dashboard_data)
                _attach_crypto(data)
                return render_to_buffer(data)
            except Exception as e:
                logger.warning("Live crypto render failed, serving cached buffer: %s", e)
        with buffer_lock:
            return epd_buffer

    def _serve_display(self):
        buf = self._fresh_or_cached_buffer()
        if not buf:
            self.send_error(503, "No render available yet")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(buf)))
        self.end_headers()
        self.wfile.write(buf)

    def _serve_status(self):
        with data_lock:
            days_count = len(dashboard_data.get("days", []))
            solar_days = len(dashboard_data.get("production_days", []))
        status = {
            "version": VERSION,
            "last_fetch": last_fetch_time,
            "last_render": last_render_time,
            "last_error": last_error,
            "days_cached": days_count,
            "buffer_ready": len(epd_buffer) > 0,
            "buffer_size": len(epd_buffer),
            "prm": PRM,
            "refresh_interval": REFRESH_INTERVAL,
            "hc_windows": os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02"),
            "ecoflow_enabled": ECOFLOW_ENABLED,
            "solar_days_cached": solar_days,
            "last_solar_report": last_solar_report,
            "crypto_enabled": CRYPTO_ENABLED,
            "last_crypto": last_crypto_time,
            "cumulus_enabled": CUMULUS_ENABLED,
            "last_cumulus": last_cumulus_report,
        }
        body = json.dumps(status, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _serve_data(self):
        with data_lock:
            body = json.dumps(dashboard_data, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _handle_refresh(self):
        threading.Thread(target=refresh_cycle, daemon=True).start()
        self.send_response(202)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Refresh triggered")

    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)


def start_http_server(port: int):
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("HTTP server on http://0.0.0.0:%d", port)
    return server


# --- Refresh Cycle ---

def refresh_cycle():
    global epd_buffer, dashboard_data
    try:
        days = fetch_and_cache()
        data = build_dashboard_data(days)
        with data_lock:
            dashboard_data = data
        buf = render_to_buffer()
        with buffer_lock:
            epd_buffer = buf
        logger.info("Refresh cycle complete — %d days, %d bytes", len(data.get("days", [])), len(buf))
    except Exception as e:
        logger.error("Refresh cycle failed: %s", e, exc_info=True)


def schedule_loop():
    while True:
        refresh_cycle()
        logger.info("Next refresh in %ds", REFRESH_INTERVAL)
        time.sleep(REFRESH_INTERVAL)


# --- Main ---

def main():
    logger.info("Linky Dashboard v%s", VERSION)

    if not TOKEN:
        logger.critical("LINKY_TOKEN environment variable is required")
        raise SystemExit(1)

    init_db()
    if ECOFLOW_ENABLED:
        start_ecoflow_listener()
    else:
        logger.info("EcoFlow integration disabled (set ECOFLOW_EMAIL/PASSWORD/DEVICE_SN to enable)")
    if CUMULUS_ENABLED:
        start_cumulus_listener()
    else:
        logger.info("Cumulus integration disabled (set CUMULUS_MQTT_HOST to enable)")
    start_http_server(PORT)
    schedule_loop()


if __name__ == "__main__":
    main()
