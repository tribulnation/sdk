# tribulnation-lighter 0.8.0

Requires SDK >=2.15.0 and typed-lighter >=0.2.0. `place_order` raises
`OrderRejected` for definitive refusals (ADR 0043).

Behaviour change: when `typed_lighter` raises `BadRequest` with a business code,
other than `21104` (invalid nonce), `place_order` now raises `OrderRejected`
instead of `BadRequest`: the API layer refused the transaction before the
sequencer saw it. `OrderRejected` subclasses `ApiError`, not `BadRequest`: an
`except BadRequest` around `place_order` no longer catches it; `except ApiError`
still does. A code-less HTTP status, any `5XX` and `21104` stay
`BadRequest`/`ApiError`. A transaction the API accepted can still be refused by the
sequencer afterwards; that surfaces as a `canceled-*` order status, not an error.

Cancellation is unchanged. Verified by unit fixtures only; no live trading run
covers `OrderRejected`.
