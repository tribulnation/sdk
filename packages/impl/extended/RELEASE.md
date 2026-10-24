# tribulnation-extended 0.1.1

Requires SDK >=2.21.0 (the release adding `Book.frozen` and `detached_books`) and
typed-extended >=0.2.0. Upgrade the SDK and this adapter together.

`depth_stream` uses the SDK's `Book.frozen` and `detached_books`
([ADR 0049](../../../dev-docs/adr/0049-book-streams-copy-on-read.md)). Extended already worked this way;
its local helpers are replaced by the SDK's, with no behaviour change.

Every other method is unchanged.

Release qualification on 2026-10-24 passed the read suites and market consistency.
Committed evidence under `release-evidence/extended/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 2.21.0 publication.
