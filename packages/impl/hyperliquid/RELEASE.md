# tribulnation-hyperliquid 0.19.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-hyperliquid >=2.6.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Breaking and behaviour changes:

1. Spot markets are SDK `SpotMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)): `balances()` reads `spotClearinghouseState` (`total`, and `total - hold` free), and `rules()` returns `SpotRules` naming the pair by token index (`base='197'`, `quote='0'` for UBTC/USDC). Spot `position`, `collateral` and `available_notional` are gone.
2. Collateral IDs use token indices: spot assets are `<account>:spot:<index>`. Every perpetual's `collateral_id()` is its dex collateral token's spot ID (`<account>:spot:0` for USDC), read from cached metadata: perpetuals and USDC-quoted spot pairs share one ID and one balance. Isolated positions return the same ID. `sdk.collateral('<account>:spot:<index>')` reads the token; token names raise `ValueError`.
3. `clearinghouseState` per dex and `spotClearinghouseState` are shared between markets and concurrent callers ([ADR 0053](../../../dev-docs/adr/0053-shared-account-reads-aster-max-leverage.md)); reads take `ttl` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)), `None` (the default) asking afresh. `userAbstraction` (account mode) is reused for a minute.
4. `leverage(refetch=...)` becomes `leverage(ttl=...)`, and leverage is no longer cached per coin; `maxLeverage` still comes from the cached dex universe, which `rules(refetch=True)` reloads.

Every other method is unchanged.
