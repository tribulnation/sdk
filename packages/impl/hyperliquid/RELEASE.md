# tribulnation-hyperliquid 0.13.0

Requires SDK >=2.13.0. New perpetual `leverage()`: the account's per-asset setting
from `activeAssetData`, capped at the asset's `maxLeverage` (falling back to it with
no usable setting). HIP-3 markets query their `dex:`-prefixed coin. Cached per coin;
`refetch=True` re-reads the setting.

Behavior change: perpetual `available_notional()` now multiplies the free collateral
by this account leverage instead of the asset's maximum leverage, so it is lower for
accounts set below the maximum. It stays an override of the SDK default, because
isolated positions are opened from the account pool. Spot `available_notional()` is
unchanged, now provided by the SDK default.

Upgrade the SDK and this adapter together.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/hyperliquid/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.13.1 publication.
