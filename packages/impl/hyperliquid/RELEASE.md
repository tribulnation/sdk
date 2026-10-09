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
