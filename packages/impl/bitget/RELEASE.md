# tribulnation-bitget 0.14.0

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-bitget >=0.6.1 (was >=0.4.1), whose private socket tracks the login per connection and reconnects after a service upgrade.

Changed:

1. Trades USDT-M perpetuals on a Unified Trading Account (behaviour change; [ADR 0064](../../../dev-docs/adr/0064-bitget-uta-perpetual-trading.md)): the `usdt` exchange places, cancels, replaces and queries cross-margin orders in one-way mode. `LIMIT` is GTC (`settings['bitget'] = {'time_in_force': 'ioc' | 'fok'}`), `POST_ONLY` post-only, `MARKET` an IOC bounded by the order price; an immediate order is read back once for its fill, and a failed read-back returns the placement with `filled_qty=None`.
2. `leverage()` is the symbol's cross setting and raises `LeverageNotSet` until one is set; `collateral_id()` is the unified pool `<account>:usdt`.
3. `cancel_open_orders` with nothing open is a no-op (Bitget answers `25204`).
4. The UTA fills stream recovers after a service upgrade (`30033`) or a lost login (`30004`).
5. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.
