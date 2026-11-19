# tribulnation-bybit 0.10.1

Requires SDK >=4.1.0, unchanged, and typed-bybit >=0.3.4 (was >=0.3.1).

Fixed:

1. Linear perpetual `available_notional()` is free collateral times the symbol's leverage setting (`leverage()`), not the contract's maximum leverage, which overstated it. Free collateral is the unified account's `totalAvailableBalance`, read in two requests instead of the account info and position sweep `perp_collateral()` makes.
2. Instruments in `PendingOpen` status (announced but not yet trading) no longer fail perpetual reads: typed-bybit 0.3.4 accepts the status that previously failed validation of the whole instruments response.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/bybit/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.

# tribulnation-bybit 0.10.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-bybit >=0.3.1, unchanged.

Changed:

1. `set_leverage(leverage)` on linear perpetuals sets buy and sell leverage on the symbol's `leverageStep`; `110043` (not modified) counts as success. `leverage()` reads `/v5/position/list` afresh.
2. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/bybit/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
