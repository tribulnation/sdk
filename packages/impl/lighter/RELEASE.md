# tribulnation-lighter 0.14.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-lighter >=0.3.2, unchanged.

Changed:

1. `set_leverage(leverage)` through `L2UpdateLeverage`, keeping the margin mode; leverages that do not divide 10000 or exceed the market maximum are refused before sending.
2. `remaining_position_limit()` reads the market's open-interest limit less its open interest.
3. A stream leaving its channel never locks it for the next subscriber: a `30003` "Already Subscribed" refusal unsubscribes the orphan and subscribes again.
4. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/lighter/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
