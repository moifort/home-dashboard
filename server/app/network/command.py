"""Network domain commands (write side): schema init + daily snapshot.

UniFi is fetched live on the hourly refresh, so there is no background listener.
"""
from app.network.infrastructure import repository


def init_schema():
    """Create the daily_unifi snapshot table (idempotent)."""
    repository.init_schema()


def start():
    """No background listener for UniFi."""
    return None


def snapshot(snap: dict):
    """Persist today's reading for the 7-day trends."""
    repository.upsert_snapshot(snap)
