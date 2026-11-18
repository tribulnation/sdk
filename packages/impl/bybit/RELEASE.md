# tribulnation-bybit 0.10.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-bybit >=0.3.1, unchanged.

Changed:

1. `set_leverage(leverage)` on linear perpetuals sets buy and sell leverage on the symbol's `leverageStep`; `110043` (not modified) counts as success. `leverage()` reads `/v5/position/list` afresh.
2. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.
