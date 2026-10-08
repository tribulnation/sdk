# tribulnation-aster 0.9.0

Requires SDK >=2.15.0 and typed-aster >=0.4.0. `place_order` raises
`OrderRejected` for definitive refusals (ADR 0043).

Behaviour changes:

1. A placement `4XX` whose body carries a business code now raises
   `OrderRejected` instead of `BadRequest`. `OrderRejected` subclasses `ApiError`,
   not `BadRequest`: an `except BadRequest` around `place_order` no longer catches
   it; `except ApiError` still does. The Binance-style codes that leave the
   execution status unknown (`-1000`, `-1001`, `-1006`, `-1007`, `-1008`), a `408`
   and a body without a code stay `BadRequest`; auth and rate-limit codes keep
   `AuthError` and `RateLimited`; a `5XX` stays ambiguous.
2. A placement whose result is `EXPIRED` or `REJECTED` with `executedQty == 0`
   (e.g. a POST_ONLY/GTX order that would have crossed, or a market order with no
   liquidity) now raises `OrderRejected` instead of returning an `OrderResponse`.

Cancellation is unchanged. Verified by unit fixtures only; no live trading run
covers `OrderRejected`.
