#!/usr/bin/env python3
"""Dashboard server for CasaOS — orchestrates the slices and serves the EPD buffer."""
import json
import logging
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path

from app import dashboard_data as dashboard
from app.system.config import (
    DATA_LEAD_MIN,
    DB_PATH,
    PARIS_TZ,
    PORT,
    RENDER_MODE,
    SAVE_PNG,
    SCREEN_REFRESH_INTERVAL_MIN,
    VERSION,
)
from app.integrations import OPTIONAL, crypto, linky
from app.system.scheduler import next_data_update, next_screen_wake
from app.rendering.converter import png_to_epd_buffer
from app.rendering.renderer import render_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

epd_buffer: bytes = b""
buffer_lock = threading.Lock()
dashboard_data: dict = {}
data_lock = threading.Lock()
last_render_time: str = ""


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
        elif self.path in ("/", "/index.html"):
            self._serve_preview()
        elif self.path == "/preview.png":
            self._serve_preview_png()
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
        """Buffer for /display: re-render at the ESP32's pull so the Home panel's
        time is the actual GET moment, with fresh crypto.

        The Home "displayed at" time and "next refresh" boundary are recomputed
        from the real wall clock here (not the build-time estimate); Linky/solar
        data stay on the hourly cache; the crypto panel is refreshed. Any failure
        falls back to the cached hourly buffer (whose Home time is the build-time
        boundary estimate)."""
        try:
            with data_lock:
                data = dict(dashboard_data)
            if not data:
                with buffer_lock:
                    return epd_buffer
            now = datetime.now(PARIS_TZ)
            data["home"] = {
                "last_text": f"{now:%H:%M}",
                "next_text": f"{next_screen_wake(now):%H:%M}",
            }
            if crypto.enabled():
                crypto.attach(data)
            return render_to_buffer(data)
        except Exception as e:
            logger.warning("Live pull render failed, serving cached buffer: %s", e)
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

    def _serve_preview(self):
        """GET / — an HTML page embedding the dashboard as a PNG, auto-refreshing
        so a browser shows the current screen (the actual 1360×480 render)."""
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Dashboard preview</title>"
            "<meta http-equiv='refresh' content='30'>"
            "<style>html,body{margin:0;height:100%;background:#222}"
            "body{display:flex;align-items:center;justify-content:center}"
            "img{max-width:100%;height:auto;border:1px solid #444;"
            "image-rendering:pixelated}</style></head>"
            "<body><img src='/preview.png' alt='Dashboard'></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _serve_preview_png(self):
        """GET /preview.png — the dashboard rendered to a PNG (the RGB image that
        feeds the EPD converter), for the browser preview. Mirrors the live pull:
        Home time + crypto are refreshed; falls back to 503 until the first build."""
        with data_lock:
            data = dict(dashboard_data)
        if not data:
            self.send_error(503, "No render available yet")
            return
        now = datetime.now(PARIS_TZ)
        data["home"] = {
            "last_text": f"{now:%H:%M}",
            "next_text": f"{next_screen_wake(now):%H:%M}",
        }
        if crypto.enabled():
            try:
                crypto.attach(data)
            except Exception as e:
                logger.warning("Preview crypto attach failed: %s", e)
        buf_io = BytesIO()
        render_dashboard(data).save(buf_io, format="PNG")
        body = buf_io.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self):
        with data_lock:
            days_count = len(dashboard_data.get("days", []))
            solar_days = len(dashboard_data.get("production_days", []))
        status = {
            "version": VERSION,
            "last_render": last_render_time,
            "days_cached": days_count,
            "buffer_ready": len(epd_buffer) > 0,
            "buffer_size": len(epd_buffer),
            "screen_refresh_interval_min": SCREEN_REFRESH_INTERVAL_MIN,
            "data_lead_min": DATA_LEAD_MIN,
            "solar_days_cached": solar_days,
        }
        status.update(linky.status())
        for integration in OPTIONAL:
            status.update(integration.status())
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
        days = linky.fetch_and_cache()
        data = dashboard.build_dashboard_data(days)
        with data_lock:
            dashboard_data = data
        buf = render_to_buffer()
        with buffer_lock:
            epd_buffer = buf
        logger.info("Refresh cycle complete — %d days, %d bytes", len(data.get("days", [])), len(buf))
    except Exception as e:
        logger.error("Refresh cycle failed: %s", e, exc_info=True)


def schedule_loop():
    """Regenerate the buffer DATA_LEAD_MIN minutes before each screen-refresh
    boundary, so the ESP32 always pulls a render that is at most a few minutes old."""
    while True:
        refresh_cycle()
        now = datetime.now(PARIS_TZ)
        target = next_data_update(now)
        sleep_s = max(1.0, (target - now).total_seconds())
        logger.info("Next data update at %s (%ds)", target.strftime("%H:%M"), int(sleep_s))
        time.sleep(sleep_s)


# --- Main ---

def main():
    logger.info("Dashboard v%s", VERSION)

    if not linky.TOKEN:
        logger.critical("LINKY_TOKEN environment variable is required")
        raise SystemExit(1)

    linky.init_schema()
    for integration in OPTIONAL:
        integration.init_schema()
        integration.start()

    start_http_server(PORT)
    schedule_loop()


if __name__ == "__main__":
    main()
