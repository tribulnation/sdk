# tribulnation-hyperliquid 0.22.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md); `PerpPosition.liquidation_price`, [ADR 0068](../../../dev-docs/adr/0068-perp-position-liquidation-price.md)) and typed-hyperliquid >=2.6.0, unchanged.

Changed:

1. `perp_position()` carries Hyperliquid's `liquidationPx` as `liquidation_price` on every dex (`None` when flat or `null`).
2. `remaining_position_limit()` shares its reads by default (`ttl` 30 s) and costs two reads shared by every coin of the dex: the leverage comes from the position in `clearinghouseState`, with no `activeAssetData` per coin. A flat coin is bounded at the asset's `maxLeverage`, the tightest bound any setting has, so a flat coin set below its maximum may read less room than the venue allows, never more.

Every other method is unchanged.
