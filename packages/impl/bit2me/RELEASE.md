# tribulnation-bit2me 0.10.2

Requires SDK >=4.1.0 and typed-bit 2me>=0.4.0, unchanged.

Fixed:

1. `depth_stream(levels=N)` serves at most `N` levels per side ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)): each subscriber reads its own copy of the shared book, trimmed to `levels`. It ignored `levels` and streamed the channel's whole book (100 levels a side).

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/bit2me/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
