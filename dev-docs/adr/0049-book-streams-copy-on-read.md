# ADR 0049: Book streams share a frozen book and copy it on read

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-10-23

## Context

Venues with diff feeds maintain one book per shared subscription with `Book.update`.
Bitget, Bybit, Kraken, MEXC and Coinbase then yielded `Book.copy()`, a `deepcopy`, on
every update. Lighter and GRVT did that and also deep-copied again for each
subscriber. On a 500-level-a-side book, one deep copy costs about 8 ms of CPU, against
0.25 ms for the update itself. Streaming all venues together starved the event loop:
websocket timeouts and ticks lagging 20 to 34 s. With the default `'latest'` inbox,
most of those copies were thrown away unread.

The guarantee the copies bought must hold: a delivered book never changes after
delivery, and a subscriber may mutate its book (`buy`, `sell`, entries) without
affecting the stream or other subscribers.

## Decision

1. `Book.update` binds new level lists and never mutates an entry. Producers yield
   `Book.frozen()`, which copies the two level lists (pointer copies) and shares the
   entries. Later updates do not change a frozen book.
2. Frozen books stay inside the stream. Every `depth_stream` passes its subscriber's
   inbox through `detached_books(stream, levels)`, which `copy()`s each book when the
   subscriber reads it. That copy has new lists and entries and shares only the
   immutable prices, quantities and time. Books replaced unread in a `'latest'` inbox
   are never copied. `skipped` is preserved.
3. `Book.copy()` builds new lists and entries directly, keeping the order, instead of
   calling `deepcopy`. The result is the same, since `Decimal` and `datetime` are
   immutable.

Extended already worked this way with local helpers; those moved into the SDK.

## Alternatives considered

1. Frozen `Book.Entry`: entries could then be shared with consumers too. It breaks
   code that edits entries; strategies build and edit `Book.Entry` objects.
2. A lazy copy-on-access `Book` subclass: it would also skip the copy for consumers
   that read only the top of the book. It adds a second `Book` type to the codec and
   to equality checks, for a cost that is already proportional to books read.
3. An incremental, bisect-based `Book.update`: it would cut the remaining
   0.25 ms per update to tens of µs. It changes what `update` does to unsorted or
   duplicate-price books, so it is left for a separate decision.

## Consequences

1. On the 500-level benchmark (`packages/sdk/test/bench_book_stream.py`), producer
   CPU per update falls from about 8 ms (16 ms on Lighter and GRVT) to about 0.29 ms.
   A book a subscriber reads costs another 0.5 ms, taken in the subscriber's turn.
2. Bitget, Bybit, Kraken, MEXC and Coinbase subscribers of one symbol no longer
   share a delivered book object; each gets its own, as Lighter, GRVT, KuCoin and
   Extended already did. KuCoin's trimmed books no longer share entries between
   subscribers.
3. dYdX still yields its live book without copying, so a later update changes a book
   its subscriber already holds. That is unchanged here.
4. Venue packages that use `Book.frozen` or `detached_books` need the SDK release
   that adds them, and their `tribulnation-sdk` floor moves with it.
