# ADR 0043: Definitive order rejections as `OrderRejected`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented for Hyperliquid, Aster and Lighter, which unit fixtures
   verify; dYdX deliberately unchanged. Not release-verified, and no live trading run
   covers it.
2. Date: 2026-10-08

## Context

A strategy whose `place_order` call fails must decide whether the order exists. Two
kinds of failure look the same today:

1. The venue processed the request and answered that the order was not accepted.
   Nothing rests and nothing filled, so re-sending immediately is safe. A hedger sending
   IOC orders (SDK `MARKET`) on Hyperliquid hits this whenever the book has nothing to
   match: "Order could not immediately match against any resting orders".
2. The outcome is unknown: a timeout, a dropped connection or a 5xx. The venue may have
   accepted the order, so re-sending can double the position.

Hyperliquid raised a bare `ApiError` for its per-order and action-level refusals. Its
HTTP transport also raises a bare `ApiError(status, body)` for every non-200 response,
5xx included. Callers could tell the two apart only by parsing messages, venue by venue.

## Decision

1. `tribulnation.sdk.OrderRejected` subclasses `ApiError`. It means the venue answered
   that the order was not accepted: nothing rests and nothing filled. Exported from
   `tribulnation.sdk` and `tribulnation.sdk.core`.
2. Ambiguous failures are never `OrderRejected`: network errors, timeouts, 5xx and other
   responses that do not establish the order's fate. They keep their current classes.
3. Venues raise it only where the venue's answer makes the refusal certain. Raising it is
   opt-in per venue; a venue that cannot tell keeps raising `ApiError` or `BadRequest`,
   so a caller may not conclude anything from the absence of `OrderRejected`.
4. Hyperliquid's `place_order` raises it for a top-level `status: "err"` (the action was
   refused before any order was processed) and for a per-order `error` status. An empty
   status list stays `ApiError`: the response does not say what happened to the order.
   Cancellation is unchanged.
5. Aster's `place_order` raises it for a `4XX` whose body carries a business code, and
   for a placement result that is `EXPIRED` or `REJECTED` with `executedQty == 0`, such as
   a GTX that would have crossed or a market order with no liquidity. Aster's API is
   Binance-style: `4XX` means the request was refused on the sender's side, while a `5XX`
   (typed-aster documents `503`) leaves the execution status unknown. The Binance codes
   that also mean "status unknown" stay `BadRequest` even on a `4XX`: `-1000` UNKNOWN,
   `-1001` DISCONNECTED, `-1006` UNEXPECTED_RESP, `-1007` TIMEOUT and `-1008` server
   busy, as do a `408` and a body without a code. Auth and rate-limit codes keep
   `AuthError` and `RateLimited`.
6. Lighter's `place_order` raises it when `typed_lighter` raises `BadRequest` with a
   business code, other than `21104` invalid nonce. `typed_lighter`'s nonce manager relies
   on the same rule: such a refusal came from the API layer before the sequencer saw the
   transaction, so its nonce is not consumed. A code-less HTTP status, any `5XX` (coded or
   not) and `21104` stay `BadRequest`/`ApiError`. A transaction the API accepted can
   still be refused by the sequencer afterwards; that surfaces as a `canceled-*` order
   status, not as an error from `place_order`.
7. dYdX's `place_order` does not raise it. `typed_dydx` broadcasts in sync mode, so a
   nonzero code is a CheckTx failure, but it raises a bare `ApiError(raw_log)` without the
   code or codespace. Some nonzero codes do not mean the transaction is dead: "tx already
   exists in cache" means the same transaction is already in the mempool. Short-term orders
   are also matched in the node's in-memory book during CheckTx rather than in blocks.
   Classifying `raw_log` text would be guesswork, so every dYdX placement error stays
   ambiguous until `typed_dydx` raises with the ABCI code and codespace, and the mapping is
   checked against the dYdX v4 CLOB error codes.
8. The gateway encodes exceptions by class name, and `OrderRejected` is in its codec
   table, so a strategy behind `ProxySDK` receives the same class.
9. `place_order` docstrings document it under `Raises:`.

## Alternatives considered

- Subclassing `BadRequest`: many venues map invalid input to `BadRequest` before the
  order is processed, and some use it for errors that do not guarantee nothing was
  placed. Promoting those would make the guarantee venue-dependent in the opposite way.
- An ambiguous-failure class (`OrderUnknown`) instead: every ambiguous path, across all
  venues and transports, would have to be re-classified before callers could trust the
  absence of it. Marking the certain case is local to the code that reads the answer.
- A flag or reason code on `ApiError`: callers would branch on attributes rather than
  `except` clauses, and the gateway would need to transport the attribute.
- Rejection details (reason enums, "would cross", "insufficient margin"): useful, but a
  separate decision. This one only fixes whether the order is known to be dead.

## Consequences

- Existing `except ApiError` handlers still catch the new class, in process and through
  a gateway whose client has the same release.
- Venues gain a verification obligation: raise `OrderRejected` only from a parsed venue
  answer, never from transport-level errors. Hyperliquid's unit fixtures pin this,
  including a 5xx staying a plain `ApiError`.
- Other venues are unchanged until each maps its definitive refusal codes.
- On Aster and Lighter, placement refusals that were `BadRequest` are now
  `OrderRejected`, which does not subclass `BadRequest`. An `except BadRequest` around
  `place_order` no longer catches them; `except ApiError` still does.
- On Aster, a placement that ends `EXPIRED`/`REJECTED` with nothing filled used to return
  an `OrderResponse`; it now raises.
- A `ProxySDK` client older than its gateway does not know the class name and decodes
  `OrderRejected` as a plain `Exception`, which its `except ApiError` no longer catches.
  Upgrade clients with or before gateways. A gateway older than the client never sends it.
- `tribulnation-hyperliquid`, `tribulnation-aster` and `tribulnation-lighter` import the
  new class, so their releases raise their `tribulnation-sdk` floors to the SDK release
  that adds it.
- `OrderRejected` says nothing about why the venue refused; re-sending may fail again for
  the same reason, so callers still bound their retries.
