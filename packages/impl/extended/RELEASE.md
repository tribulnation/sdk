# tribulnation-extended 0.5.2

Requires SDK >=4.2.0 (unchanged) and typed-extended >=0.2.2 (was >=0.2.0).

Fixed:

1. Market reads no longer fail on the market status `REDUCE_ONLY_OI`. Extended reports it for a market whose open interest is above its `openInterestLimit`, where only reduce-only orders are accepted (SKHY-USD on 2026-11-28). typed-extended 0.2.2 accepts the status.
2. `markets()` lists `REDUCE_ONLY_OI` markets, like `REDUCE_ONLY`; `rules().api` is false for them (#415).
