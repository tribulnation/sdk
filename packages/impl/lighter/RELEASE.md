# tribulnation-lighter 0.11.1

Requires SDK >=2.21.0 (the release adding `Book.frozen` and `detached_books`) and
typed-lighter >=0.3.0. Upgrade the SDK and this adapter together.

`depth_stream` no longer deep-copies the whole order book on every update: the
stream yields `Book.frozen()` and each subscriber gets its own copy, through
`detached_books`, of each book it reads ([ADR 0049](../../../dev-docs/adr/0049-book-streams-copy-on-read.md)).
On a 500-level-a-side book, the work per update falls from about 16 ms (it copied twice) to about
0.3 ms, plus about 0.5 ms for each book a subscriber reads. Delivered books keep their
guarantees: a later push never changes them, and a subscriber may mutate its own.

Every other method is unchanged.
