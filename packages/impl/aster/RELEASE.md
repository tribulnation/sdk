# tribulnation-aster 0.2.0 release candidate

Moves to `typed-aster` 0.2.0, adds bulk perpetual statistics and supports
Python 3.10.

- `perp_stats` returns index, mark, predicted funding, next funding time and
  funding interval for all or the selected perpetuals, from the unfiltered premium
  index and funding configuration (two requests). Open interest is `None`: Aster
  has no bulk source. A symbol without a published interval reports
  `funding_interval=None`.
- `next_funding` raises `MissingData` when the venue publishes no funding interval
  for the symbol, instead of failing validation.
- `requires-python` is now `>=3.10`, matching the other implementations.

Spot balances, trade history, funding payments, available notional and perpetual
collateral remain unsupported. Wallet, Earn and Report are not routed. See
dev-docs/aster-market.md.

Requires tribulnation-sdk >=2.4.0 and typed-aster >=0.2.0; 0.2.0 adds a required
client transport, so earlier `typed-aster` versions are incompatible.

Release qualification records mainnet public read suites and Market consistency
against the pinned Catalogue snapshot. Account and trading methods were verified
live on testnet only; private mainnet behavior is unverified.
