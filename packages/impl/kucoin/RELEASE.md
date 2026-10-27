# tribulnation-kucoin 0.7.0

Requires SDK >=3.0.0 (spot and margin market types, collateral IDs and read `ttl`) and typed-kucoin >=0.4.1. Upgrade the SDK and this adapter together: SDK 3.0 changes the base classes this adapter subclasses, so older adapters do not work with it, and this one does not work with SDK 2.

Markets drop the account stubs SDK 3.0 removes from spot ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)); they raised `NotImplementedError` before. The reads SDK 3.0 gives a `ttl` accept it and ignore it: every read asks the venue ([ADR 0054](../../../dev-docs/adr/0054-caller-chosen-read-staleness.md)).

Every other method is unchanged.

Release qualification on 2026-10-27 passed the read suites and market consistency.
Committed evidence under `release-evidence/kucoin/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 3.0.0 publication.
