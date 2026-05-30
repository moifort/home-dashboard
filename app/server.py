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
from app.config import DB_PATH, PARIS_TZ, PORT, REFRESH_INTERVAL, RENDER_MODE, SAVE_PNG, VERSION
from app.integrations import OPTIONAL, crypto, linky
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
        if crypto.enabled():
            try:
                with data_lock:
                    data = dict(dashboard_data)
                crypto.attach(data)
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
            "last_render": last_render_time,
            "days_cached": days_count,
            "buffer_ready": len(epd_buffer) > 0,
            "buffer_size": len(epd_buffer),
            "refresh_interval": REFRESH_INTERVAL,
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
    while True:
        refresh_cycle()
        logger.info("Next refresh in %ds", REFRESH_INTERVAL)
        time.sleep(REFRESH_INTERVAL)


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
