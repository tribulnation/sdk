# tribulnation-kucoin 0.6.1

Requires SDK >=2.21.0 (the release adding `Book.frozen` and `detached_books`) and
typed-kucoin >=0.4.1. Upgrade the SDK and this adapter together.

`depth_stream` copies each book through the SDK's `detached_books`, only when a
subscriber reads it ([ADR 0049](../../../dev-docs/adr/0049-book-streams-copy-on-read.md)). KuCoin's books are
small snapshots, so the gain is small; trimmed books no longer share entries between
subscribers.

Every other method is unchanged.

Release qualification on 2026-10-24 passed the read suites and market consistency.
Committed evidence under `release-evidence/kucoin/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 2.21.0 publication.
