# tribulnation-aster 0.15.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-aster >=0.7.0, unchanged.

Changed:

1. `set_leverage(leverage)` sets the symbol's leverage (whole multiples).
2. `remaining_position_limit()` reads the leverage bracket's `maxNotional` and the symbol's remaining open-interest allowance.
3. An order refused for its position limit raises `PositionLimitExceeded` (an `OrderRejected`).
4. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.
