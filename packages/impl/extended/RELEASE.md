# tribulnation-extended 0.5.2

Requires SDK >=4.2.0 (unchanged) and typed-extended >=0.2.2 (was >=0.2.0).

Fixed:

1. Market reads no longer fail on the market status `REDUCE_ONLY_OI`. Extended reports it for a market whose open interest is above its `openInterestLimit`, where only reduce-only orders are accepted (SKHY-USD on 2026-11-28). typed-extended 0.2.2 accepts the status.
2. `markets()` lists `REDUCE_ONLY_OI` markets, like `REDUCE_ONLY`; `rules().api` is false for them (#415).

Release qualification on 2026-11-28 with typed-extended 0.2.2 (read-only, mainnet, account mode `private`): surfaces 29 passed, 0 failed, 3 declared exclusions; market consistency 582 pass, 1 deferred, 3 recorded limitations (ADR 0048 RFQ indicative tickers). Committed evidence under `release-evidence/extended/` matches pinned Catalogue `e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; `sdk-dev results release extended` is `verified`.
