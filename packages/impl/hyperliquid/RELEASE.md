# tribulnation-hyperliquid 0.21.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-hyperliquid >=2.6.0, unchanged.

Changed:

1. `set_leverage(leverage)` keeps the coin's margin mode.
2. `remaining_position_limit()` reads `perpsAtOpenInterestCap` and the margin table at the account's leverage; refusals for those limits raise `PositionLimitExceeded` and `OpenInterestCapped`.
3. `settings['hyperliquid'] = {'fast_cancel': True}` signs Hyperliquid's fast-cancel flag into every cancel; a refused fast cancel is raised, never resent without it.
4. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/hyperliquid/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
