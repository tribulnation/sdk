# tribulnation-lighter 0.15.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md); `PerpPosition.liquidation_price`, [ADR 0068](../../../dev-docs/adr/0068-perp-position-liquidation-price.md)) and typed-lighter >=0.3.2, unchanged.

Changed:

1. `perp_position()` carries Lighter's `liquidation_price` (`None` when flat or `0`).
2. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): the open-interest room comes from the all-market `market_stats` snapshot, shared by every market.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/lighter/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.2.0 publication.
