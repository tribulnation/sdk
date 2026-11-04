# tribulnation-lighter 0.13.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-lighter >=0.3.0, unchanged. Upgrade the SDK and this adapter together: this adapter does not work with SDK 3.

New and behaviour changes:

1. Creates, modifies and single-order cancels go through one batcher per client ([ADR 0057](../../../dev-docs/adr/0057-lighter-batched-order-transactions.md)). A lone transaction goes through `sendTx` as before; those submitted while one is in flight, or in the same event-loop turn, leave together in one `sendTxBatch` (at most 15). A refused batch raises `ApiError` for each of its transactions, never `OrderRejected`.
2. `place_order(order, settings={'lighter': {'replaces': id}})` moves resting order `id` to the order's price and size with one `L2ModifyOrder`. `MARKET` orders, `time_in_force` and `reduce_only` raise `ValueError` beside it; a refused modify is `BadRequest`.
3. A cancel of an order already gone is dropped by the sequencer unreported, so Lighter never raises `OrderNotFound`. `replace_order(s)` use the SDK default.

Every other method is unchanged.

Release qualification on 2026-11-03 passed the read suites and market consistency.
Committed evidence under `release-evidence/lighter/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.0.0 publication.
