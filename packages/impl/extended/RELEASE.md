# tribulnation-extended 0.5.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md)) and typed-extended >=0.2.0, unchanged.

Changed:

1. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): the all-market `markets`, positions and leverage reads, one request each shared by every market, instead of per-market reads.

Every other method is unchanged.
