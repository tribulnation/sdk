# tribulnation-risex 0.2.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md)) and typed-risex >=0.1.1, unchanged.

Changed:

1. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): one all-market live request, shared by every market, instead of a per-market read.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/risex/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.2.0 publication.
