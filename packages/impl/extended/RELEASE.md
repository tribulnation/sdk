# tribulnation-extended 0.3.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-extended >=0.2.0, unchanged. `replace_order(s)` use the SDK default (cancel, then place); Extended cancels asynchronously, so a cancel of a gone order is not reported as `OrderNotFound`.

New:

1. Setting `settings['extended'] = {'time_in_force': 'IOC'}`: a `LIMIT` order is sent with `timeInForce` `IOC` (immediate-or-cancel), on order-book and RFQ markets, without an explicit expiry. Set on a `MARKET` or `POST_ONLY` order it raises `ValueError` before signing. Without it, `LIMIT` orders are unchanged.

Every other method is unchanged.

Release qualification on 2026-11-04 passed the read suites and market consistency.
Committed evidence under `release-evidence/extended/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
