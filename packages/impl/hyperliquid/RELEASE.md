# tribulnation-hyperliquid 0.22.1

Requires SDK >=4.2.0 and typed-hyperliquid >=2.6.0, unchanged.

Fixed:

1. Spot tickers report each pair's own 24h volume. Each pair now takes its volume from its own asset context, matched by `coin`, instead of by position; since the first delisted index, pairs had been reading another pair's volume.

Every other method is unchanged.
