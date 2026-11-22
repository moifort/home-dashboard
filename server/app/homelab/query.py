"""Home lab domain queries (read side): attach the panel the reader cached."""
from datetime import datetime

from app.homelab import command
from app.system.config import PARIS_TZ


def attach(data: dict):
    """Attach the cached panel. With no fresh copy (first render after a start,
    or Komodo silent for a while) Komodo is read on the spot; when that fails
    too the key is left unset, so the row is simply omitted."""
    panel = command.current() or command.refresh()
    if panel:
        data["homelab"] = panel


def status() -> dict:
    from app.homelab import ENABLED

    read_at = command.last_read()
    return {"homelab_enabled": ENABLED,
            "last_homelab": datetime.fromtimestamp(read_at, PARIS_TZ).isoformat() if read_at else ""}
