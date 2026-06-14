#!/usr/bin/env python3
"""Dashboard server for CasaOS — orchestrates the slices and serves the EPD buffer.

No render cache: every request builds the dashboard fresh from the local SQLite
store (the MQTT integrators' single source of truth), so the screen always shows
the current data. Reads are local and instantaneous, so there is nothing to cache;
a build/render failure simply returns 503 and the ESP32 retries at its next wake.
"""
import json
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
from app.registry import CORE, OPTIONAL
from app.rendering.converter import png_to_epd_buffer
from app.rendering.renderer import render_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

last_render_time: str = ""


# --- Rendering (Pillow) ---

def build_fresh(now: datetime) -> dict:
    """Build the full render dict from the local store, current as of `now`.

    `build_dashboard_data` reads each domain's table (and live-fetches the
    resilient crypto/UniFi panels, which omit themselves on failure), then the
    Home panel is overridden with the real pull moment + the device's next wake."""
    data = dashboard.build_dashboard_data(CORE.load_days())
    data["home"] = dashboard.build_home_live(now)
    return data


def render_to_buffer(data: dict) -> bytes:
    global last_render_time
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
    # The server is single-threaded: without a socket timeout, one client that
    # opens a connection and never sends its request (or dies mid-read) would
    # block every further /display pull. A silent connection is dropped instead.
    timeout = 60

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/display":
            self._serve_display(parse_qs(parsed.query))
        elif path in ("/", "/index.html"):
            self._serve_preview()
        elif path == "/preview.png":
            self._serve_preview_png()
        elif path == "/status":
            self._serve_status()
        elif path == "/api/data":
            self._serve_data()
        else:
            self.send_error(404)

    def _serve_display(self, params):
        """GET /display — the EPD buffer, rendered fresh from the current data.

        The Home panel's "displayed at" time is the real GET moment and "next
        refresh" the device's next wake. The ESP32's telemetry query params
        (boot/reason/fail) are recorded first so the rendered Home reflects this
        pull. A build/render failure returns 503; the ESP32 keeps its current
        image and retries at its next scheduled wake."""
        now = datetime.now(PARIS_TZ)
        # Generic pull hook: any enabled optional domain exposing record_pull
        # ingests the device telemetry carried on the /display request.
        for integration in OPTIONAL:
            record = getattr(integration, "record_pull", None)
            if record and integration.enabled():
                try:
                    record(params, now)
                except Exception as e:
                    logger.warning("record_pull failed for %s: %s", integration.__name__, e)
        try:
            buf = render_to_buffer(build_fresh(now))
        except Exception as e:
            logger.error("Display render failed: %s", e, exc_info=True)
            self.send_error(503, "Render failed")
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
        feeds the EPD converter), for the browser preview. Built fresh like
        /display; a build/render failure returns 503."""
        try:
            img = render_dashboard(build_fresh(datetime.now(PARIS_TZ)))
            buf_io = BytesIO()
            img.save(buf_io, format="PNG")
            body = buf_io.getvalue()
        except Exception as e:
            logger.error("Preview render failed: %s", e, exc_info=True)
            self.send_error(503, "Render failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_status(self):
        """GET /status — lightweight health/diagnostics (no render, no network):
        version, last /display render, the day count and each domain's status."""
        status = {
            "version": VERSION,
            "last_render": last_render_time,
            "days_cached": len(CORE.load_days()),
            "screen_refresh_interval_min": SCREEN_REFRESH_INTERVAL_MIN,
            "data_lead_min": DATA_LEAD_MIN,
        }
        status.update(CORE.status())
        for integration in OPTIONAL:
            status.update(integration.status())
        body = json.dumps(status, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_data(self):
        """GET /api/data — the full render dict, built fresh (debug introspection)."""
        try:
            body = json.dumps(build_fresh(datetime.now(PARIS_TZ)), indent=2).encode()
        except Exception as e:
            logger.error("Data build failed: %s", e, exc_info=True)
            self.send_error(503, "Build failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)


# --- Main ---

def main():
    logger.info("Dashboard v%s", VERSION)

    CORE.init_schema()
    CORE.start()
    for integration in OPTIONAL:
        integration.init_schema()
        integration.start()

    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    logger.info("HTTP server on http://0.0.0.0:%d", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
