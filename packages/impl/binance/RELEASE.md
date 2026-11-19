# tribulnation-binance 0.9.1

Requires SDK >=3.0.0 and typed-binance >=1.6.0, unchanged.

Fixed:

1. `depth_stream(levels=N)` on spot and USD-M perpetuals, and USD-M REST `depth(levels=N)`, serve at most `N` levels per side ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)): books are trimmed to `levels` instead of returning the whole 5/10/20 stream tier or REST limit tier that covers it.

Changed:

1. The Market support declaration names the market kinds served, `spot` and `perp` ([ADR 0056](../../../dev-docs/adr/0056-market-kind-aware-support.md)); nothing else in it changed.

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/binance/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
