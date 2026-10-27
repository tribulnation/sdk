# tribulnation-grvt 0.2.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`). Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

`collateral_id()` is the trading sub-account's cross pool, `<account>:<exchange>` ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)); it funds isolated positions too.

`leverage(refetch=...)` becomes `leverage(ttl=...)` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)). Leverage is no longer cached per instrument: one account-wide `all_initial_leverage` answer serves every instrument, asked afresh without a `ttl` and shared with one. Other account reads accept `ttl` and ignore it.

Every other method is unchanged.
