"""SQLite connection primitive (transverse infrastructure).

The single place that opens the database file. Each domain owns its own tables
and accessors in its `infrastructure/repository.py`; this module only provides the
shared `connect()` so every repository talks to the same configured DB.
"""
import os
import sqlite3

from app.system.config import DB_PATH


def connect() -> sqlite3.Connection:
    """Open a connection to the configured database file."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)
