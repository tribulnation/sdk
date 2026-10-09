# tribulnation-hyperliquid 0.17.0

Requires SDK >=2.17.0 and typed-hyperliquid >=2.5.0. Placements report
`OrderResponse.filled_qty`.

New:

1. `OrderResponse.filled_qty` is the `filled` status's `totalSz`, final for `MARKET`
   and IOC orders. A `resting` answer carries no fill size, and a GTC order that
   partly crosses on arrival also answers `resting`, so `filled_qty` is `None` there.

Every other method is unchanged. Verified by unit fixtures only; no live trading run
covers `filled_qty`.

The SDK floor rises to 2.17.0, whose `OrderResponse` declares `filled_qty`. Upgrade
the SDK and this adapter together.

Release qualification on 2026-10-09 passed the read suites and market
consistency. Committed evidence under `release-evidence/hyperliquid/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.17.0 publication.
