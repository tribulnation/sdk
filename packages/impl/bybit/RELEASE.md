# tribulnation-bybit 0.9.0

Requires SDK >=4.0.0 and typed-bybit >=0.3.1, unchanged. It is released with SDK 4.0 ([ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and its evidence.

Changed:

1. Spot `tickers()` returns only pairs that `instruments-info` lists, the same set `markets()` returns. Bybit's tickers endpoint also served an unlisted pair (`SOLBRL`, with no bid or ask, on 2026-11-04), which used to come back too.

Every other method is unchanged.

Release qualification on 2026-11-04 passed the read suites and market consistency.
Committed evidence under `release-evidence/bybit/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.0.0 publication.
