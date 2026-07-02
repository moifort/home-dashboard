"""SQLite connection primitive (transverse infrastructure).

The single place that opens the database file. Each domain owns its own tables
and accessors in its `infrastructure/repository.py`; this module only provides the
shared `connect()` so every repository talks to the same configured DB.
"""
import os
import sqlite3
from contextlib import contextmanager

from app.system.config import DB_PATH


def connect() -> sqlite3.Connection:
    """Open a connection to the configured database file.

    WAL lets the ~6 MQTT writer threads and the HTTP render thread proceed
    concurrently instead of contending on the rollback journal; busy_timeout
    makes a residual collision wait instead of raising `database is locked`
    (which the MQTT on_message guards would swallow, silently losing a persist).
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction():
    """Scoped connection for repository calls: commit on success, always close.

    Replaces the connect/commit/close boilerplate every repository repeated;
    committing on read-only paths is a no-op."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
