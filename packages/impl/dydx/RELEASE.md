# tribulnation-dydx 0.13.0

Requires SDK >=2.13.0. New perpetual `leverage()`: `1 / effective initial margin
fraction`, the market's fraction adjusted upward by open-interest caps. dYdX has no
per-account setting, so it is the same for every subaccount, cross or isolated.
`refetch=True` reloads the market list shared with `rules()`.

`available_notional()` is unchanged (subaccount `freeCollateral` × the same
leverage), now provided by the SDK default rather than an override.

Upgrade the SDK and this adapter together.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/dydx/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.13.1 publication.
