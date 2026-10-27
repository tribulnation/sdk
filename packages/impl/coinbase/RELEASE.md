# tribulnation-coinbase 0.6.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-coinbase >=0.4.0. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Spot markets no longer serve `position`, `collateral` and `available_notional` through the SDK interface: SDK 3.0 removes them from spot markets ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)). Spot `balances` and collateral IDs are not mapped yet.

The reads SDK 3.0 gives a `ttl` accept it and ignore it: every read asks the venue ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)).

Every other method is unchanged.
