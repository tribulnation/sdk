# tribulnation-dydx 0.22.1

Requires SDK >=4.1.0, typed-core >=0.11.0 and typed-dydx >=3.8.0, unchanged.

Fixed:

1. `depth(levels=N)` and `depth_stream(levels=N)` serve at most `N` levels per side ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)); both ignored `levels` and returned the Indexer's full book.
2. `depth_stream()` gives each subscriber its own copy of the shared book instead of the shared book itself.

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
