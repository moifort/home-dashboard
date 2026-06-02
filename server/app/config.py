"""Global paths, build version and process-wide settings.

Constants that are not specific to any single integration. Per-slice configuration
(integration env vars, ENABLED flags) lives in each integration's own config.py.
"""
import os
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

# Server root (the Python import root): server/app/config.py -> server/app -> server.
REPO_ROOT = Path(__file__).resolve().parents[1]

PARIS_TZ = ZoneInfo("Europe/Paris")
DAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

# Screen-refresh schedule (see app/schedule.py). The ESP32 wakes every
# SCREEN_REFRESH_INTERVAL_MIN minutes (clock-aligned, must match REFRESH_INTERVAL_MIN
# in the firmware); the server regenerates the buffer DATA_LEAD_MIN minutes before
# each of those boundaries so the ESP always pulls a fresh render.
SCREEN_REFRESH_INTERVAL_MIN = int(os.environ.get("SCREEN_REFRESH_INTERVAL_MIN", "120"))
DATA_LEAD_MIN = int(os.environ.get("DATA_LEAD_MIN", "10"))
RENDER_MODE = os.environ.get("RENDER_MODE", "4color")
DB_PATH = os.environ.get("DB_PATH", "/data/linky.db")
PORT = int(os.environ.get("PORT", "5000"))
SAVE_PNG = os.environ.get("SAVE_PNG", "false").lower() == "true"


def get_version() -> str:
    version_file = REPO_ROOT / ".version"
    if version_file.exists():
        return version_file.read_text().strip()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


VERSION = get_version()
