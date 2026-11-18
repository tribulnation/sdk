# tribulnation-grvt 0.4.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)), typed-grvt >=0.2.0 and typed-core >=0.13, unchanged.

Changed:

1. `settings['grvt'] = {'time_in_force': 'IMMEDIATE_OR_CANCEL'}` sends a `LIMIT` order immediate-or-cancel; on `MARKET` or `POST_ONLY` it raises `ValueError` before signing.
2. `set_leverage(leverage)` through the signed `set_position_config`, keeping the margin type (up to 6 decimals, within the instrument's bounds; needs the signer key).
3. `remaining_position_limit()` reads `max_position_size` less the position held in each direction.
4. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/grvt/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
