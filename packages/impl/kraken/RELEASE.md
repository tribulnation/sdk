# tribulnation-kraken 0.9.3

Requires SDK >=4.1.0 and typed-kraken >=0.6.1, unchanged.

Fixed:

1. Perpetual `replace_order` sends one `editorder` by order ID and never re-places an order that no longer rests. Before, an edit of a filled or cancelled order sent a fresh full-size order.
2. No `orders/status` lookup before each edit: sides of orders placed or listed through the client are remembered, so the edit goes out alone. Unknown IDs are looked up once.
3. `editorder` statuses map to: `edited` returns the response; `orderForEditNotFound`, `notFound` and `filled` without executions raise `OrderNotFound`; `postWouldExecute` raises `OrderRejected` (Kraken cancelled the order); any other refusal raises `ApiError` with the order unchanged.
4. A side flip cancels then places, and no longer places when the cancel finds the order gone.

Every other method is unchanged.

Release qualification on 2026-11-24 passed the read suites and market consistency.
Committed evidence under `release-evidence/kraken/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
