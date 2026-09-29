# tribulnation-aster 0.3.0 release candidate

Client order IDs, order IDs on fills, and perpetual trade history.

- `place_order` sends `Order['client_order_id']` unchanged as `newClientOrderId`
  (perpetuals take up to 36 of `A-Z a-z 0-9 . : / _ -`); `None` or no key lets the
  venue generate one. `random_client_order_id()` returns 32 random hex digits.
- Fills report `Trade.order_id`, and streamed fills also `Trade.client_order_id`.
- `PerpMarket.trades_history` reads inclusive bounds in native seven-day windows up to
  the current time, each paged and retried inside the SDK request boundary. Its fills
  carry `order_id`; the venue's history rows have no client order ID.

Spot trade history stays unsupported: on testnet, spot `userTrades` omits confirmed
buy fills. Spot balances, funding payments, available notional and perpetual
collateral remain unsupported. See dev-docs/aster-market.md.

Requires tribulnation-sdk >=2.7.0 (`Order['client_order_id']`, `Trade.order_id` and
`Trade.client_order_id`, ADR 0029) and typed-aster >=0.2.0.

Release qualification records mainnet public read suites and Market consistency
against the pinned Catalogue snapshot. Account and trading methods, including
perpetual trade history, were verified on testnet only. Client order IDs and order IDs
on fills are covered by unit fixtures; no live trading round trip is recorded.
