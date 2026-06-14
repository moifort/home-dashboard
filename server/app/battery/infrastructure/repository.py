"""Battery domain repository — the only place that touches battery_cycles.

One row per battery cycle: a run from a power-on (battery recharged / first boot)
until the last seen pull before the next power-on. `started_at`/`ended_at` are ISO
local timestamps stamped by the server at each /display pull, `wakes` counts the
pulls in the cycle, `last_boot` keeps the firmware's RTC bootCount of the most
recent pull (so a reset-to-1 boot can be detected as a new cycle even if the reset
reason is missing). No backfill: history starts at the first reporting firmware.
"""
from app.module.db import connect


def init_schema():
    """Create the battery_cycles table (idempotent)."""
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS battery_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            wakes INTEGER NOT NULL,
            last_boot INTEGER
        )"""
    )
    conn.commit()
    conn.close()


def _row(r) -> dict:
    return {"id": r[0], "started_at": r[1], "ended_at": r[2],
            "wakes": r[3], "last_boot": r[4]}


def get_last_cycle() -> dict | None:
    """The current (most recent) cycle, or None if none recorded yet."""
    conn = connect()
    cur = conn.execute(
        "SELECT id, started_at, ended_at, wakes, last_boot FROM battery_cycles "
        "ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    return _row(row) if row else None


def get_cycles() -> list[dict]:
    """Every cycle, oldest first. The last one is the current (open) cycle; the
    rest are completed runs whose ended_at marks where that charge ran out."""
    conn = connect()
    cur = conn.execute(
        "SELECT id, started_at, ended_at, wakes, last_boot FROM battery_cycles "
        "ORDER BY id"
    )
    rows = [_row(r) for r in cur.fetchall()]
    conn.close()
    return rows


def insert_cycle(started_at: str, boot: int | None):
    """Open a new cycle (a power-on): ended_at starts equal to started_at."""
    conn = connect()
    conn.execute(
        "INSERT INTO battery_cycles (started_at, ended_at, wakes, last_boot) "
        "VALUES (?, ?, 1, ?)",
        (started_at, started_at, boot),
    )
    conn.commit()
    conn.close()


def update_cycle(cycle_id: int, ended_at: str, wakes: int, boot: int | None):
    """Extend the current cycle with a new pull (deep-sleep wake)."""
    conn = connect()
    conn.execute(
        "UPDATE battery_cycles SET ended_at = ?, wakes = ?, last_boot = ? WHERE id = ?",
        (ended_at, wakes, boot, cycle_id),
    )
    conn.commit()
    conn.close()
