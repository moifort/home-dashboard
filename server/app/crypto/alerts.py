"""Crypto domain alerts — the "Crypto" status-board section (alpha vs hold)."""
from app.module.format import AlertRule, _to_float, _usd, _usd_fmt


def _crypto_alpha_gain(crypto, alpha):
    """$ the strategy earned over buy-and-hold = invested x alpha%.
    invested = portfolio - profit. Returns None if the amounts can't be parsed."""
    portfolio = _usd(crypto.get("portfolio_text"))
    profit = _usd(crypto.get("profit_text"))
    if portfolio is None or profit is None:
        return None
    return (portfolio - profit) * alpha / 100


def _crypto_alpha_neg(data):
    c = data.get("crypto") or {}
    alpha = _to_float(c.get("alpha_text"))
    if alpha is None or alpha >= 0:
        return None
    gain = _crypto_alpha_gain(c, alpha)
    money = f"manque {_usd_fmt(gain)}$" if gain else ""
    return ("Bot derrière le hold", f"{round(alpha)}%", money)


def _crypto_alpha_pos(data):
    c = data.get("crypto") or {}
    alpha = _to_float(c.get("alpha_text"))
    if alpha is None or alpha <= 0:
        return None
    gain = _crypto_alpha_gain(c, alpha)
    money = f"gain {_usd_fmt(gain)}$" if gain else ""
    return ("Bot devant le hold", f"+{round(alpha)}%", money)


RULES = [
    AlertRule("crypto_alpha_neg", _crypto_alpha_neg, "Crypto", 30, False),
    AlertRule("crypto_alpha_pos", _crypto_alpha_pos, "Crypto", 3, True),
]

BOARDS = [
    ("Crypto", lambda data: bool(data.get("crypto"))),
]
