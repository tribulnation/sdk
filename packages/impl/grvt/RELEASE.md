# tribulnation-grvt 0.5.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md); `PerpPosition.liquidation_price`, [ADR 0068](../../../dev-docs/adr/0068-perp-position-liquidation-price.md)), typed-grvt >=0.2.0 and typed-core >=0.13, unchanged.

Changed:

1. `perp_position()` carries GRVT's `est_liquidation_price` as `liquidation_price` (`None` when flat or named `0`).
2. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): every perpetual position from one shared request; the instrument's ticker is shared for `ttl` and not read where no cap is published.

Every other method is unchanged.
