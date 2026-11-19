"""Home lab domain commands (write side): nothing to write.

Komodo stores the history itself and is read live on each refresh, so there is
no table to create and no background listener to start.
"""


def init_schema():
    """No table: Komodo keeps the stats."""
    return None


def start():
    """No background listener for Komodo."""
    return None
