"""Status-board aggregator — collects each domain's alert rules into the board.

The rules themselves live in each domain's alerts.py (electricity, water, solar,
network, crypto), declared as AlertRule descriptors. This module is the
cross-domain part: it runs every rule, groups the active items under their board
section, and returns the rows the renderer draws.

A *bad* alert renders entirely red, a *good* highlight entirely black — red means
a problem, black a positive note. Every rule guards on data.get(...) so a removed
domain (its data key absent) simply never fires. The board shows one row per
*monitored* section (its source data present), in the canonical DOMAINS order.
"""
from app.crypto import alerts as crypto_alerts
from app.electricity import alerts as electricity_alerts
from app.network import alerts as network_alerts
from app.solar import alerts as solar_alerts
from app.water import alerts as water_alerts

# Domain alert modules, in attach/registry order. Each exposes RULES (a list of
# AlertRule) and BOARDS (a list of (label, present_fn)).
_DOMAIN_ALERTS = (electricity_alerts, water_alerts, solar_alerts, network_alerts, crypto_alerts)

# Every rule, flattened across domains. Order is irrelevant to the rendered board
# (it sorts by severity); kept stable for predictability.
_RULES = [rule for mod in _DOMAIN_ALERTS for rule in mod.RULES]

# Board section presence predicates, keyed by label.
_BOARD_PRESENT = {label: fn for mod in _DOMAIN_ALERTS for label, fn in mod.BOARDS}

# Canonical order of the board's rows (the order quiet sections are listed in).
DOMAINS = ["EDF", "Eau", "Solaire", "Réseau", "Prises"]


def build_alerts(data: dict) -> list[dict]:
    """Run every enabled rule; return the raw active items (grouping happens in
    build_board). Each item is {"key", "message", "figure", "money", "severity",
    "good", "board"}; a rule may omit the trailing money string. A rule that
    raises is treated as 'no alert' — a render must never crash on a bad value.
    """
    alerts = []
    for rule in _RULES:
        if not rule.enabled:
            continue
        try:
            res = rule.fn(data)
        except Exception:
            res = None
        if res:
            message, figure = res[0], res[1]
            money = res[2] if len(res) > 2 else ""
            alerts.append({
                "key": rule.key, "message": message, "figure": figure, "money": money,
                "severity": rule.severity, "good": rule.good, "board": rule.board,
            })
    return alerts


def build_board(data: dict) -> list[dict]:
    """Build the always-on status board rows the renderer draws.

    One row per *monitored* domain that has active items (quiet domains are
    omitted entirely), most severe first (problems above positives):
        {"label": dom, "alert": True, "severity": int,
         "items": [(message, figure, money, good), ...]}
    The board is empty when no monitored domain has anything to report (the
    renderer then shows a single "Tout va bien" section).
    """
    by_domain = {}
    for a in build_alerts(data):
        by_domain.setdefault(a["board"], []).append(a)

    rows = []
    for dom in DOMAINS:
        present = _BOARD_PRESENT.get(dom)
        if not present or not present(data):
            continue
        items = by_domain.get(dom)
        # Quiet domains (nothing to report) are dropped — only domains with active
        # items get a section, so the panel never shows a "Rien à signaler" row.
        # When every domain is quiet the board is empty and the renderer falls
        # back to a single "Tout va bien" section.
        if not items:
            continue
        items.sort(key=lambda a: a["severity"], reverse=True)
        n_bad = sum(1 for a in items if not a["good"])
        rows.append({
            "label": dom, "alert": True, "severity": items[0]["severity"], "n_bad": n_bad,
            "items": [(a["message"], a["figure"], a["money"], a["good"]) for a in items],
        })

    # Vertical space is limited, so list the domains with the most problems first,
    # then by severity (domains with only positive notes naturally come last).
    rows.sort(key=lambda r: (-r["n_bad"], -r["severity"]))
    return rows
