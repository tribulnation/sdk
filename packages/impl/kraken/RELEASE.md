# tribulnation-kraken 0.9.2

Requires SDK >=4.1.0 and typed-kraken >=0.6.1, unchanged.

Fixed:

1. Spot REST `depth(levels=N)` caps Kraken's `count` at 500 ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)): a larger count was answered with Kraken's 100-level default instead of its deepest book.

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/kraken/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
