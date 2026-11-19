"""Home lab domain: the servers Komodo watches (the `home lab` row of the arcade UI).

Komodo already polls every server and keeps the history, so this domain owns no
table and no listener: on each refresh it lists the servers and reads their last
24 hours of stats from the Komodo Core API, then folds them into one column per
hour (the hour's highest CPU and memory use, so a short spike stays visible).
The point of entry exposes the uniform slice API (enabled / init_schema / start /
attach / status). Remove the whole folder to drop it.
"""
import os

URL = os.environ.get("KOMODO_URL", "").rstrip("/")
API_KEY = os.environ.get("KOMODO_API_KEY", "")
API_SECRET = os.environ.get("KOMODO_API_SECRET", "")

ENABLED = bool(URL and API_KEY and API_SECRET)


def enabled() -> bool:
    return ENABLED


from app.homelab.command import init_schema, start  # noqa: E402
from app.homelab.query import attach, status  # noqa: E402

__all__ = ["enabled", "init_schema", "start", "attach", "status",
           "ENABLED", "URL", "API_KEY", "API_SECRET"]
