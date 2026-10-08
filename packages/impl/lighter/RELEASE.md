# tribulnation-lighter 0.7.0

Requires SDK >=2.14.0. Adds a read-only credential mode and public account reads.

New:

1. A read-only auth token (`auth_token`, or `LIGHTER_AUTH_TOKEN` /
   `LIGHTER_TESTNET_AUTH_TOKEN`) serves `fees`, `open_orders`, `query_order`,
   `trades_history`, `trades_stream`, `funding_payments` and every account read
   without an API key. Trading methods raise `AuthError` naming the missing API key.
2. Without credentials, `position`, `collateral`, `perp_position`,
   `perp_collateral`, `leverage`, `available_notional` and `trades_history` read the
   configured `account_index`, or else the master account (`account_type` 0) of the
   configured `address`. `fees`, orders, `trades_stream` and `funding_payments`
   still need a token or API key; the venue rejects unauthenticated funding reads
   for master accounts. See ADR 0040.

Behaviour change: spot `collateral()` on a classic (non-unified) account raises
`NotImplementedError` instead of `ApiError`.

If the network's API key variables are set, the client uses them even for an
account configured with only a token.

Testnet verification: 24 maker and taker fills on perpetual and spot markets each
charged exactly the `fees()` rate, and every trading method was exercised.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/lighter/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.14.0 publication.
