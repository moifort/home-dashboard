"""GraphQL queries for the crypto-bot API."""

STATS_QUERY = (
    "query { stats { totalProfitUsdc sommeMiseUsdc sandboxMode"
    " periodStats { alltime { holdReturnPercent } } } }"
)

# Grid snapshot: bounds + level count + current price (Stats), plus the 7-day
# price line (PriceHistory). Mirrors the iOS GridSnapshotCard inputs.
GRID_QUERY = (
    "query {"
    " stats { currentPrice gridConfig { lowerPrice upperPrice levels } }"
    " priceHistory { time price }"
    " }"
)
