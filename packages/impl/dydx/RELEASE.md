# tribulnation-dydx 0.21.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-dydx >=3.7.0, unchanged. Upgrade the SDK and this adapter together: this adapter does not work with SDK 3.

No adapter code changes. `place_orders` returns the SDK 4.0 per-order results and `replace_order(s)` use the SDK default (cancel, then place). The market support declaration names its kinds (`perp`, [ADR 0056](../../../dev-docs/adr/0056-market-kind-aware-support.md)).

Every other method is unchanged.

Release qualification on 2026-11-03 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.0.0 publication.
