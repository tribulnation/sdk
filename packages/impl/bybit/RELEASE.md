# tribulnation-bybit 0.10.3

Requires SDK >=4.1.0 and typed-bybit >=0.3.5, unchanged.

Fixed:

1. `depth_stream(levels=N)` serves at most `N` levels per side ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)): each subscriber's copy of the shared book is trimmed to `levels`, which was ignored.

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/bybit/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
