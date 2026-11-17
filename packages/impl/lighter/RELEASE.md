# tribulnation-lighter 0.13.2

Requires SDK >=4.0.0, unchanged, and typed-lighter >=0.3.2 (was >=0.3.0), which adds `create_order(..., price_protection=...)`.

New:

1. `place_order(order, settings={'lighter': {'price_protection': False}})` skips Lighter's fat-finger check (`21733`, "order price flagged as an accidental price") on a new perpetual order. That check refuses an ask below `max(mark, best bid) x 0.95` or a bid above `min(mark, best ask) x 1.05`, even when the book really trades there (a thin book that has moved more than 5 % from the mark). The mark-price filter (`21734`) still applies. Unset, nothing changes. A batched order (`sendTxBatch`) is never checked by Lighter. Beside `replaces` the setting raises `ValueError`.

Every method is unchanged.

Release qualification on 2026-11-16 passed the read suites and market consistency.
Committed evidence under `release-evidence/lighter/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows typed-lighter 0.3.2 publication.
