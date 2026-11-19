# tribulnation-kucoin 0.7.1

Requires SDK >=3.0.0 and typed-kucoin >=0.4.1, unchanged.

Fixed:

1. `levels` is an upper bound ([ADR 0071](../../../dev-docs/adr/0071-depth-levels-upper-bound.md)): `depth(levels=N)` above 100 and `depth_stream(levels=N)` above 5 are served at that maximum instead of raising `ValueError`. Only `levels < 1` still raises.

Changed:

1. The Market support declaration names the market kinds served, `spot` and `perp` ([ADR 0056](../../../dev-docs/adr/0056-market-kind-aware-support.md)), and its note describes the depth caps.

README: logo header.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/kucoin/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
