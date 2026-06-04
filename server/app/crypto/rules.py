"""Crypto domain business rules — pure derivations from raw bot stats.

No IO: turns the GraphQL `stats` block into the render-ready panel fields.
"""
from app.crypto.infrastructure.graphql.transport import _grouped


def build_crypto_panel(stats: dict) -> dict:
    """Derive the display fields used by the renderer from raw stats.

    Mirrors CryptoBotWidget.swift (small family): percentage return, signed
    profit, portfolio value and sandbox flag.
    """
    profit = stats.get("totalProfitUsdc", 0.0)
    somme_mise = stats.get("sommeMiseUsdc", 0.0)

    pct = (profit / somme_mise * 100) if somme_mise > 0 else 0.0
    sign = "+" if profit >= 0 else "-"
    portfolio = somme_mise + profit

    # Alpha = the bot's return minus the buy-and-hold return over the same
    # (all-time) period: how much the strategy beat just holding BTC.
    hold = ((stats.get("periodStats") or {}).get("alltime") or {}).get("holdReturnPercent")
    alpha = (pct - hold) if hold is not None else None

    return {
        "pct_text": f"{pct:+.0f}",
        "profit_positive": profit >= 0,
        "profit_text": f"{sign}${_grouped(abs(profit))}",
        "portfolio_text": f"${_grouped(portfolio)}",
        "alpha_text": f"{alpha:+.0f}" if alpha is not None else "",
        "alpha_positive": alpha is None or alpha >= 0,
        "sandbox": bool(stats.get("sandboxMode", False)),
    }
