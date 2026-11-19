# tribulnation-nado 0.2.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md)), typed-nado >=0.1.0 and typed-core >=0.14, unchanged.

Changed:

1. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): `all_products` and the perpetual index/mark prices, one request each shared by every market; an uncapped market reads nothing.

Every other method is unchanged.
