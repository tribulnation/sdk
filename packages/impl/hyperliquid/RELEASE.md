# tribulnation-hyperliquid 0.12.1

Fix: in unified-account mode, `perp_collateral().free_collateral` is now the
collateral token's spot `total - hold`, matching Hyperliquid's "available to
trade". It previously used `tokenToAvailableAfterMaintenance`, which nets out
only maintenance margin and overstated opening capacity (about 2x).
`initial_margin` (`equity - free_collateral`) is now the hold. Equity and
maintenance margin are unchanged, and `available_notional()` now agrees with
`free_collateral`. Other margin modes are unaffected.

Requires SDK >=2.12.0, unchanged from 0.12.0.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/hyperliquid/` matches
pinned Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes.
