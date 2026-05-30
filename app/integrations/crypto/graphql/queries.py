"""GraphQL queries for the crypto-bot API."""

STATS_QUERY = (
    "query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode"
    " periodStats { alltime { holdReturnPercent } } } }"
)

# Grid snapshot: bounds + level count + current price (Stats), the 7-day price
# line (PriceHistory), and the last placement cycle's skipped levels — the
# warning markers shown on the grid. Mirrors the iOS GridSnapshotCard inputs.
GRID_QUERY = (
    "query {"
    " stats { currentPrice gridConfig { lowerPrice upperPrice levels } }"
    " priceHistory { time price }"
    " placementStatus { cycleAt skippedLevels { price side reason { kind } } }"
    " }"
)
