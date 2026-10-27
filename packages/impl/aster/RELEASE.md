# tribulnation-aster 0.13.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-aster >=0.7.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Breaking and behaviour changes:

1. Spot markets are SDK `SpotMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)): `balances()` (`free` and `locked` of the spot wallet), `rules()` returns `SpotRules` with the pair's asset symbols, and `collateral_ids()` returns `<account>:spot:<asset>`. `SpotExchange.balance(asset)` reads one asset. Spot `position`, `collateral` and `available_notional` are gone. Spot balances are mainnet only.
2. Every perpetual's `collateral_id()` is the futures wallet, `<account>:perp`: spot and futures wallets are separate.
3. Perpetual positions, collateral and leverage come from one all-symbol `positionRisk` request and the futures account, shared between symbols and concurrent callers ([ADR 0053](../../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)). Reads take `ttl` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)): `None` (the default) asks afresh, a `timedelta` reuses an answer that recent. A symbol missing from the all-symbol answer is read alone.
4. `leverage(refetch=...)` becomes `leverage(ttl=...)`, and leverage is no longer cached per symbol: without a `ttl` each call reads `positionRisk`.
5. Perpetual orders run at the symbol's highest allowed leverage ([ADR 0053](../../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)). Before a symbol's first order in a client's lifetime, `place_order` reads its leverage brackets and sets the leverage to bracket 1's `initialLeverage` when it differs (once, under a per-symbol lock). If that check fails the order is sent anyway. On a `-2027` refusal the leverage is set again (at most once every 10 s) and the order resent once; if it cannot be set, the original `OrderRejected` is raised. **This changes the account's leverage setting on Aster.**

Every other method is unchanged.
