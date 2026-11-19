# ADR 0070: Book paths rely on the book-order invariant

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends [0049](0049-book-streams-copy-on-read.md) (its third
   alternative and the gateway's copy on read); implemented, not release-verified
2. Date: 2026-11-19

## Context

`Book.bids` and `Book.asks` are documented best-first, and the gateway protocol sends
them that way. Profiling the engine's gateway and workers with py-spy found the book
paths still paying for that order again and again:

1. `Book.__post_init__` re-sorted both sides on every construction, including every
   book msgspec decoded from the gateway: 7 to 13% of worker CPU.
2. `best_bid`/`best_ask` scanned the whole side with `max`/`min`: about 9%.
3. `Book.update` rebuilt a price dict and re-sorted the whole book on every delta,
   about 15% of gateway CPU on Lighter's feeds. ADR 0049 left an incremental update
   for a separate decision, since it changes what `update` does to unsorted books or
   repeated prices.
4. `detached_books` copied every level of every book the gateway read, about 29% of
   gateway CPU with the garbage collection the entries cause, although the gateway
   only encodes the books.

## Decision

1. The book-order invariant is load-bearing: every path that builds a book from
   outside levels sorts, every SDK path that derives or maintains a book keeps the
   order, and readers rely on it.
2. `__post_init__` sorts both sides in place with an `attrgetter` key, as before but
   cheaper. It runs for the constructor and for every book msgspec decodes from the
   gateway wire: the wire order is not trusted. Sorting a side that is already in
   order is nearly linear and costs less than checking the order first (about 45 µs
   against 55 to 80 µs for a pure-Python check, 500 levels a side), so input keeps
   being sorted, not validated. Only `presorted` skips the sort, for levels the SDK
   itself keeps in order: `copy`, `frozen` and `limit`, which slices without
   re-sorting.
3. `best_bid` and `best_ask` return the first level and raise `ValueError` on an
   empty side, as the scans did.
4. `update` locates each changed price by binary search in copies of the two lists,
   then removes crossed levels as before. It still binds new lists and never edits an
   entry (ADR 0049). It requires a book in book order. A changed or removed price
   replaces all levels at that price; repeated prices the update does not touch are
   kept, where the dict version merged them into the last one.
5. A task that never mutates the books it reads may set the `reading_books_only`
   context variable. `detached_books` then hands it the shared frozen books, trimmed,
   without copying. The gateway sets it in each stream task, which only encodes
   books. Every other subscriber still gets its own copy.
6. `Book.Entry` stays a mutable dataclass, and `copy` still makes new entries.

## Alternatives considered

1. A frozen `Book.Entry`, so `copy` could share entries: rejected again, as in ADR
   0049. `buy`/`sell` and strategy code edit entries, and the sharing tests assert a
   copy's entries are its own.
2. A trusted flag on the constructor or a checked O(n) order test: the flag widens
   the public constructor for what `presorted` already does internally, and the check
   is slower than the sort it would skip.
3. A separate wire-only `Book` struct in the codec: it would change the schema's type
   names or need a conversion step on every message.
4. A `depth_stream` argument to skip the copy: it changes the Market contract of
   every venue, while only the gateway needs it.
5. Trusting the wire order, by sorting in an `__init__` msgspec does not call: an
   earlier draft of this record accepted it. Withdrawn: a peer sending levels out of
   order would yield books whose `best_bid`, `best_ask` and `update` are wrong, and
   the sort it saves is a small share of a decode.

## Consequences

1. On 500 levels a side (`packages/sdk/test/bench_book_hot_paths.py`), construction
   of sorted levels falls from about 77 to 48 µs, a wire decode, still sorting, from
   about 775 to 750 µs, `best_bid` + `best_ask` from 82 to 0.2 µs, and an update of 1
   to 4 levels a side from about 114 to 14 µs. The gateway no longer spends about 255 µs copying
   each streamed book it reads.
2. Code that appends to or reorders `bids`/`asks` by hand and then reads `best_bid`,
   `best_ask` or `update`s the book gets wrong results; it must keep the order or
   rebuild the book with the constructor.
3. A gateway peer that sends levels out of order, against the protocol, still yields
   sorted books.
4. `reading_books_only` is inherited by tasks created while it is set. The gateway
   sets it only in its stream tasks, whose subscriptions create producer tasks that
   do not read `detached_books`.
5. Only the SDK package changes. Venue packages need no release and no floor bump to
   benefit; their streams already build deltas with the constructor and maintain
   books with `update` and `frozen`.
