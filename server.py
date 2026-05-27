#!/usr/bin/env python3
"""Linky dashboard server for CasaOS — fetches electricity data and serves EPD buffer."""
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from converter import png_to_epd_buffer
from linky_client import (
    LinkyApiError,
    LinkyAuthError,
    compute_daily_hc_hp,
    fetch_load_curve,
    parse_hc_windows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
TEMPLATES_DIR = ROOT / "templates"

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
DITHER = os.environ.get("DITHER", "none")
DB_PATH = os.environ.get("DB_PATH", "/data/linky.db")
PORT = int(os.environ.get("PORT", "5000"))
SAVE_PNG = os.environ.get("SAVE_PNG", "false").lower() == "true"

epd_buffer: bytes = b""
buffer_lock = threading.Lock()
dashboard_data: dict = {}
data_lock = threading.Lock()
last_fetch_time: str = ""
last_render_time: str = ""
last_error: str = ""


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
    conn.commit()
    conn.close()


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
    # 5 weeks of history for stats comparison
    full_start = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    if not needs_refresh(week_start, end_date):
        logger.info("Cache is fresh, skipping API call")
        return get_cached_days(full_start, end_date)

    # API limits to 7 days per request — fetch in weekly chunks
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
    return {"days": result, "stats": stats, "last_updated": now.isoformat()}


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


# --- Rendering ---

browser_instance = None
page_instance = None
pw_instance = None


def init_browser():
    global browser_instance, page_instance, pw_instance
    logger.info("Launching Chromium...")
    pw_instance = sync_playwright().start()
    browser_instance = pw_instance.chromium.launch(
        headless=True,
        args=[
            "--disable-lcd-text",
            "--disable-font-subpixel-positioning",
            "--font-render-hinting=none",
        ],
    )
    page_instance = browser_instance.new_page(
        viewport={"width": 1360, "height": 480},
    )
    logger.info("Browser ready")


def render_to_buffer() -> bytes:
    global last_render_time
    page_instance.goto(f"http://127.0.0.1:{PORT}/")
    page_instance.wait_for_selector("body.ready", timeout=5000)
    png_bytes = page_instance.screenshot(type="png")

    if SAVE_PNG:
        out = Path(DB_PATH).parent / "last_render.png"
        out.write_bytes(png_bytes)
        logger.info("Saved screenshot to %s", out)

    buf = png_to_epd_buffer(png_bytes, mode=RENDER_MODE, dither=DITHER)
    last_render_time = datetime.now(PARIS_TZ).isoformat()
    logger.info("Rendered EPD buffer: %d bytes", len(buf))
    return buf


# --- HTTP Server ---

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/display":
            self._serve_display()
        elif self.path == "/" or self.path == "/dashboard":
            self._serve_html()
        elif self.path.startswith("/static/"):
            self._serve_static()
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

    def _serve_display(self):
        with buffer_lock:
            buf = epd_buffer
        if not buf:
            self.send_error(503, "No render available yet")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(buf)))
        self.end_headers()
        self.wfile.write(buf)

    def _serve_static(self):
        rel_path = self.path.lstrip("/")
        file_path = ROOT / rel_path
        if file_path.exists() and file_path.is_file():
            self.send_response(200)
            ct = "application/octet-stream"
            if file_path.suffix == ".woff2":
                ct = "font/woff2"
            elif file_path.suffix == ".woff":
                ct = "font/woff"
            elif file_path.suffix == ".css":
                ct = "text/css"
            self.send_header("Content-Type", ct)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_error(404)

    def _serve_html(self):
        html_path = TEMPLATES_DIR / "dashboard.html"
        html = html_path.read_text()
        with data_lock:
            data_json = json.dumps(dashboard_data)
        html = html.replace(
            "window.__DASHBOARD_DATA__ = {};",
            f"window.__DASHBOARD_DATA__ = {data_json};",
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_status(self):
        with data_lock:
            days_count = len(dashboard_data.get("days", []))
        status = {
            "last_fetch": last_fetch_time,
            "last_render": last_render_time,
            "last_error": last_error,
            "days_cached": days_count,
            "buffer_ready": len(epd_buffer) > 0,
            "buffer_size": len(epd_buffer),
            "prm": PRM,
            "refresh_interval": REFRESH_INTERVAL,
            "hc_windows": os.environ.get("HC_WINDOWS", "23:32-5:32,15:02-17:02"),
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
    if not TOKEN:
        logger.critical("LINKY_TOKEN environment variable is required")
        raise SystemExit(1)

    init_db()
    start_http_server(PORT)
    init_browser()
    schedule_loop()


if __name__ == "__main__":
    main()
