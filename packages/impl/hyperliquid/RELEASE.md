# tribulnation-hyperliquid 0.15.0

Requires SDK >=2.15.0 and typed-hyperliquid >=2.5.0. `place_order` raises
`OrderRejected` for definitive refusals (ADR 0043).

Behaviour change: a top-level `status: "err"` (the action was refused before any
order was processed) and a per-order `error` status (e.g. an IOC/`MARKET` order
that could not immediately match) now raise `OrderRejected` instead of a bare
`ApiError`. `OrderRejected` subclasses `ApiError`, so `except ApiError` still
catches it. An empty status list and non-200 HTTP responses, 5xx included, stay
plain `ApiError`: they do not say what happened to the order.

Cancellation is unchanged. Verified by unit fixtures only; no live trading run
covers `OrderRejected`.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/hyperliquid/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.15.0 publication.
