"""GraphQL queries for the crypto-bot API."""

STATS_QUERY = (
    "query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode"
    " periodStats { alltime { holdReturnPercent } } } }"
)

# Grid snapshot: bounds + level count + current price (Stats), the 7-day price
# line (PriceHistory), the completed trades plotted on it (Trades) and the last
# placement cycle's skipped levels — the warning markers shown on the grid.
# Mirrors the iOS GridSnapshotCard inputs.
# `limit` only caps COMPLETED trades (active positions always come back): 100 is
# a wide margin over what a 7-day window holds, and out-of-window ones are dropped.
TRADES_LIMIT = 100
GRID_QUERY = (
    "query {"
    " stats { currentPrice gridConfig { lowerPrice upperPrice levels } }"
    " priceHistory { time price }"
    f" trades(limit: {TRADES_LIMIT}) {{ status profitUsdc"
    " buyOrder { price filledAt } sellOrder { price filledAt } }"
    " placementStatus { cycleAt skippedLevels { price side reason { kind } } }"
    " }"
)
