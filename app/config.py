"""Global paths, build version and process-wide settings.

Constants that are not specific to any single integration. Per-slice configuration
(integration env vars, ENABLED flags) lives in each integration's own config.py.
"""
import os
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

# Repo root: app/config.py -> app/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = REPO_ROOT / "fonts"

PARIS_TZ = ZoneInfo("Europe/Paris")
DAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "3600"))
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
