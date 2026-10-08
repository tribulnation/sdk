# tribulnation-aster 0.7.0

Requires SDK >=2.13.0. New perpetual `leverage()`: the symbol's configured initial
leverage, from its `positionRisk` rows (one per side in hedge mode; the lower is
used should they differ). A missing row raises `MissingData`. Cached per symbol;
`refetch=True` reads it again.

Perpetual `available_notional()`, previously unsupported, is now the SDK default:
the cross bucket's `availableBalance` times `leverage()`. Like `collateral()`, it
raises `NotImplementedError` for isolated positions, and it ignores the leverage
bracket's notional cap.

Upgrade the SDK and this adapter together.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/aster/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.13.1 publication.
