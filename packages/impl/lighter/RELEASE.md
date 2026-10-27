# tribulnation-lighter 0.12.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-lighter >=0.3.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Breaking and behaviour changes:

1. Spot markets are SDK `SpotMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)): `balances()` and `SpotExchange.balance(asset)`. A margin-enabled asset (USDC) totals its `margin_balance`, shared with perpetuals, and frees `available_balance - locked_balance`; any other asset is its spot `balance` less `locked_balance`. Spot rules and collateral IDs name assets by numeric id (`<account>:spot:3` is USDC). Classic accounts raise `NotImplementedError` for spot balances. Spot `position`, `collateral` and `available_notional` are gone.
2. A perpetual's `collateral_id()` is spot USDC (`<account>:spot:3`) on a unified account and `<account>:perp` on a classic one; isolated positions return the same ID.
3. Positions, collateral and leverage come from one `/account` request shared between markets and concurrent callers ([ADR 0053](../../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)); reads take `ttl` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)), `None` (the default) asking afresh. `leverage(refetch=...)` becomes `leverage(ttl=...)` and is no longer cached per market.
4. The `market_stats` snapshots (`tickers`, `perp_stats`, `next_funding`) stay single-flight whatever the `ttl`, since a connection refuses a second subscription to an open channel; `None` only skips a stored snapshot.

Every other method is unchanged.
