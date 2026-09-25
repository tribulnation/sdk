# tribulnation-lighter 0.1.0 release candidate

First release: perpetual and spot Market support for Lighter, on `typed-lighter`
0.1.1. Exchange IDs are `perp` and `spot`; market and asset ids are the venue's numeric
ids.

- Public: discovery, tickers, rules, REST depth (top 250 orders per side), shared
  full-book streams, six candle intervals, perpetual index, `perp_stats`, next funding
  and funding-rate history.
- Account and trading: fees, order queries, open orders, trade history and streams,
  positions, cross and isolated perpetual collateral, unified-account spot collateral,
  available notional, funding payments, MARKET, LIMIT and POST_ONLY orders and every
  cancellation path.

Requires tribulnation-sdk >=2.6.0 (`Rules.fee_asset: str | None`, ADR 0028) and
typed-lighter >=0.1.1. `MarketSDK` routing (`accounts.Lighter`, venues `lighter` and
`lighter_testnet`) ships with the same SDK release.
