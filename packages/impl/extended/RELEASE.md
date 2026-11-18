# tribulnation-extended 0.4.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-extended >=0.2.0, unchanged.

Changed:

1. `set_leverage(leverage)` through `PATCH /user/leverage` (decimals accepted; Extended is cross-only).
2. `remaining_position_limit()` reads the margin schedule's position-value cap at the account's leverage less the position, bounded by the market's open-interest limit.
3. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.
