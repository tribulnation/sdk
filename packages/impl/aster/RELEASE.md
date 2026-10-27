# tribulnation-aster 0.13.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-aster >=0.7.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Breaking and behaviour changes:

1. Spot markets are SDK `SpotMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)): `balances()` (`free` and `locked` of the spot wallet), `rules()` returns `SpotRules` with the pair's asset symbols, and `collateral_ids()` returns `<account>:spot:<asset>`. `SpotExchange.balance(asset)` reads one asset. Spot `position`, `collateral` and `available_notional` are gone. Spot balances are mainnet only.
2. Every perpetual's `collateral_id()` is the futures wallet, `<account>:perp`: spot and futures wallets are separate.
3. Perpetual positions, collateral and leverage come from one all-symbol `positionRisk` request and the futures account, shared between symbols and concurrent callers ([ADR 0053](../../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)). Reads take `ttl` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)): `None` (the default) asks afresh, a `timedelta` reuses an answer that recent. A symbol missing from the all-symbol answer is read alone.
4. `leverage(refetch=...)` becomes `leverage(ttl=...)`, and leverage is no longer cached per symbol: without a `ttl` each call reads `positionRisk`.
5. An order refused because the symbol's leverage setting is above the maximum Aster now allows (`-2027`, seen when Aster lowers a symbol's maximum) lowers the setting to that maximum (bracket 1's `initialLeverage`) and is resent once [ADR 0055](../../../dev-docs/adr/0055-aster-lower-leverage-on-refusal.md). Concurrent refusals share one fix, which stands for 10 s. The adapter never raises a leverage setting and reads nothing before an order; if the setting is not above the maximum, or cannot be lowered, the original `OrderRejected` is raised.

Every other method is unchanged.
