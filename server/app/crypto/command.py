"""Crypto domain commands (write side).

Crypto is fetched live on each pull: no persistent storage and no background
listener, so the lifecycle hooks are intentional no-ops kept for the uniform
slice API.
"""


def init_schema():
    """No persistent storage: crypto is fetched live on each pull."""


def start():
    """No background listener for crypto."""
    return None
