"""Assemble the render data dict: Linky core + each enabled optional slice.

Thin orchestrator. The core consumption days/stats come from the Linky slice;
every optional integration contributes its own fields via attach().
"""
from datetime import datetime

from app.config import PARIS_TZ
from app.integrations import OPTIONAL, linky


def build_dashboard_data(days: list[dict]) -> dict:
    data = linky.build_core(days)
    data["last_updated"] = datetime.now(PARIS_TZ).isoformat()
    for integration in OPTIONAL:
        if integration.enabled():
            integration.attach(data)
    return data
