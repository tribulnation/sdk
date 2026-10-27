# tribulnation-margin-trade 0.2.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-margin-trade >=0.1.1. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Breaking and behaviour changes:

1. Spot markets are SDK `SpotMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)): `balances()` and `SpotExchange.balance(asset)` read `total` and `total - hold`; spot tokens are `<account>:spot:<symbol>` collateral IDs (`margin-trade:spot:USDC`). Spot `position`, `collateral` and `available_notional` are gone.
2. Every perpetual's `collateral_id()` is the perp wallet, `<account>:perp`.
3. `fees()` returns the market's `rules().fees`, the rates its fills are charged, instead of raising `NotImplementedError`.
4. `leverage(refetch=...)` becomes `leverage(ttl=...)` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)) and is no longer cached forever. Other account reads accept `ttl`.

Every other method is unchanged.

Release qualification on 2026-10-27 passed the read suites and market consistency.
Committed evidence under `release-evidence/margin-trade/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 3.0.0 publication.
