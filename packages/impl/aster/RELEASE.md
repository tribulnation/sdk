# tribulnation-aster 0.16.1

Requires SDK >=4.2.0 and typed-aster >=0.7.0, unchanged.

Fixed:

1. `depth_stream(levels=N)` no longer raises for `N` above 20: `levels` is an upper bound. The default `'depth'` source subscribes to the smallest partial-depth tier (5, 10 or 20) holding `min(N, 20)` and trims books to `N`, so `levels=50` serves 20 levels and `levels=7` reads `@depth10` and keeps 7. `'fast'` and `'bbo'` serve at most 5 and 1. Spot `'depth'` at 5 levels or fewer shares the `'fast'` feed (`@depth5@100ms`).
2. REST `depth(levels=N)` caps at 1000 levels instead of raising. Only `levels < 1` still raises `ValueError`.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/aster/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
