# tribulnation-extended 0.2.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-extended >=0.2.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

`leverage(refetch=...)` becomes `leverage(ttl=...)` ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)). Leverage is no longer cached per market: without a `ttl` each call asks the venue; with one, concurrent and recent callers share one answer. Other account reads accept `ttl` and ignore it.

`collateral_id()` is not mapped yet and raises `NotImplementedError` ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)).

Every other method is unchanged.
