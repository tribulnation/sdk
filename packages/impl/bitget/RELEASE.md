# tribulnation-bitget 0.11.1

Requires SDK >=2.21.0 (the release adding `Book.frozen` and `detached_books`) and
typed-bitget >=0.4.1. Upgrade the SDK and this adapter together.

`depth_stream` no longer deep-copies the whole order book on every update: the
stream yields `Book.frozen()` and each subscriber gets its own copy, through
`detached_books`, of each book it reads ([ADR 0049](../../../dev-docs/adr/0049-book-streams-copy-on-read.md)).
On a 500-level-a-side book, the work per update falls from about 8 ms to about
0.3 ms, plus about 0.5 ms for each book a subscriber reads. Delivered books keep their
guarantees: a later push never changes them, and a subscriber may mutate its own.

Subscribers of the same symbol used to share one delivered book object; each now gets
its own.

The trading methods' `NotImplementedError` messages and docs now read "trading is not
supported for Bitget".

Every other method is unchanged.

Release qualification on 2026-10-24 passed the read suites and market consistency.
Committed evidence under `release-evidence/bitget/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 2.21.0 publication.
