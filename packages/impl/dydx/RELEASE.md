# tribulnation-dydx 0.20.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-dydx >=3.7.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Perpetual markets are SDK 3.0 `MarginMarket`s ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)). `collateral_id()` is the subaccount pool that margins new orders: `<account>:perp` for the parent subaccount, `<account>:perp.<N>` for child subaccount `N`. Nothing moves collateral between subaccounts on placement.

Account reads accept `ttl` and ignore it: every read asks the indexer ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)). `leverage(refetch=...)` becomes `leverage(ttl=...)`; leverage still derives from the cached market list.

Every other method is unchanged.

Release qualification on 2026-10-27 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 3.0.0 publication.
