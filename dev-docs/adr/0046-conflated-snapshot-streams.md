# ADR 0046: Conflate snapshot streams before decoding, and report skipped books

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented for Binance, Aster and Hyperliquid depth streams,
   unit-tested and benchmarked with a local synthetic burst. Not release-verified.
2. Date: 2026-10-19

## Context

Book streams default to `queue_size=1, overflow='latest'`: a slow subscriber skips to
the newest book. The conflation happened only at the subscriber's inbox, so every frame
was still decoded by the typed client and, on Aster, converted into a `Book` before the
inbox discarded it; Binance ignored `queue_size`/`overflow` and delivered every frame.
Under load (a data release, a busy loop), that work saturated the loop and a backlog
built up before the inbox, so subscribers read books seconds old (sdk#230). The typed
clients now take `keep_latest` on every stream (typed-core 0.12.0): one slot per
subscription that keeps the newest raw frame, decodes it on read and counts the frames
it replaced as `skipped`.

## Decision

1. A subscriber is latest-only when it asks for `queue_size=1, overflow='latest'`
   (`tribulnation.sdk.core.latest_only`). Only then may a venue subscribe with typed
   `keep_latest`, and only for feeds whose every frame is the full state of that
   subscription: Binance spot and USD-M partial depth, Aster partial depth and
   per-symbol `bookTicker`, Hyperliquid `l2Book` and `bbo`. Never for diffs, trades,
   fills, account events, or all-symbol feeds.
2. A shared upstream (`Subscription`) opens with its `subscribe_latest` connector while
   every subscriber is latest-only. A subscriber that is not (e.g. `overflow='fail'` to
   capture every book) reopens it without conflation; it then stays unconflated until
   it closes. Frames are never dropped silently for a subscriber that asked for them.
3. Every stream that knows how many books its subscriber never saw exposes `skipped:
   int` (the `Skipping` protocol): typed's skipped frames while the subscriber was
   subscribed plus its own inbox's `'latest'` drops. `tribulnation.sdk.core.skipped(stream)`
   reads it, returning None for streams that do not count.
4. The exchange-to-receive delay is not added: typed records no receive time, and
   `Book.time` already carries the exchange time, so a consumer reads the age of a book
   as `now - book.time`.

## Alternatives considered

1. Conflating every shared upstream unconditionally: simpler, but a subscriber with
   `overflow='fail'` would lose books silently, breaking the documented capture mode.
2. A second, unconflated typed subscription beside the conflated one: the typed client
   refuses a second subscription to the same channel on one connection.
3. A richer per-stream statistics object (delays, rates): no consumer needs more than
   the count yet; it can be added on top of `Skipping` later.

## Consequences

1. Under a burst, the newest delivered book stays within one loop turn of the newest
   frame received, and skipped frames cost only their receive (Binance and Aster route
   raw frames; Hyperliquid still decodes to route but skips validation and conversion).
2. Binance depth streams now honour the latest-only default; other `queue_size` or
   `overflow` values keep delivering every frame, unbounded, as before.
3. A non-latest-only subscriber joining a conflated feed causes a brief resubscribe of
   that feed for its other subscribers.
4. The venue packages need the SDK release that adds `latest_only`, `Skipping` and
   `SkippingView`; their `tribulnation-sdk` floor moves with that release.
5. Gateway-proxied streams report only the proxy-side inbox's drops.
