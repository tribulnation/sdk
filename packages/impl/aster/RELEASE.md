# tribulnation-aster 0.1.0 release candidate

First release: spot and linear perpetual Market support for Aster, on
`typed-aster` 0.1.0. Exchange IDs are `spot` and `perp`, with native symbols such
as `BTCUSDT`.

- Public: discovery, tickers, rules, REST depth (1–1000 levels), shared depth
  streams (1–20 levels), six candle intervals, perpetual index, next funding and
  funding-rate history.
- Account and trading: fees, order queries, open orders, fill streams, MARKET,
  LIMIT (GTC) and POST_ONLY (GTX) orders and every cancellation path; one-way,
  cross-margin perpetual position and collateral.

Spot balances, trade history, funding payments, bulk perpetual statistics,
available notional and perpetual collateral remain unsupported. Wallet, Earn and
Report are not routed; `tribulnation.aster.Report` is testnet-verified only. See
dev-docs/aster-market.md.

Requires tribulnation-sdk >=2.4.0 and typed-aster >=0.1.0. `MarketSDK` routing
(`accounts.Aster`, venues `aster`/`aster_testnet`) ships with the next SDK release;
until then use `AsterMarket.new()` directly.

Release qualification records mainnet public read suites and Market consistency
against the pinned Catalogue snapshot. Account and trading methods were verified
live on testnet only; private mainnet behavior is unverified.
