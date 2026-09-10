# ADR 0005: Explicit Bitget futures product identities

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; coin identity amended by [ADR 0008](0008-bitget-classic-and-uta-coin.md)
2. Date: 2026-09-10

## Context

Bitget's previous `perp` exchange meant only USDT futures. Catalogue instruments
also include USDC and coin-margined products. A generic exchange ID obscures that
scope, and some coin Catalogue keys use web/UTA rather than Classic API symbols.

## Decision

1. Expose `spot`, `usdt`, `usdc`, and `coin`. Replace the former `perp` ID with
   `usdt`; do not retain an alias that discovery and the Catalogue do not share.
2. Use the selected Classic API product's native symbol unchanged: e.g.
   `BTCUSDT`, `BTCPERP`, and `BTCUSD`. Product-keyed caches prevent cross-product
   collisions. Delivery contracts are not perpetual markets.
3. Extend public rules, books, tickers, candles, funding and perpetual statistics
   across all three futures products. Keep new USDC/coin account methods explicitly
   unimplemented; this decision does not expand trading or portfolio support.
4. Coordinate Catalogue updates through user-reviewed PRs. Preserve unresolved
   instruments for investigation rather than infer delistings from one listing.

## Alternatives considered

1. Keep `perp` for USDT: preserves existing IDs but leaves an asymmetric and
   misleading name alongside the newly supported products.
2. Retain a `perp` alias: introduces multiple exchange IDs for the same market and
   complicates identity validation and stored-data migration.
3. Use web/UTA IDs: mismatches the Classic endpoints backing this implementation.

## Consequences

Consumers must migrate qualified USDT IDs from `bitget:perp:*` to `bitget:usdt:*`
(including configured account aliases). Catalogue exchange changes and verified
coin symbol changes are coordinated, not silently normalized by the SDK.

Coin futures use the base coin as the fee asset. `minTradeUSDT` becomes `min_value`
only for USDT futures; it is unknown in USD/USDC quote units without conversion.
Live response-validation failures and unresolved Catalogue identities still block
qualification. Acceptance does not certify release readiness or authorize release.
