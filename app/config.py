"""Global paths and build version.

Process-wide constants that are not specific to any single integration. Per-slice
configuration (env vars, ENABLED flags) lives in each integration's own config.py.
"""
import subprocess
from pathlib import Path

# Repo root: app/config.py -> app/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = REPO_ROOT / "fonts"


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
