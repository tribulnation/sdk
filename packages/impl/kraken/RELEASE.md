# tribulnation-kraken 0.7.1

Requires SDK >=2.17.0 and typed-kraken >=0.4.0. `trades_history` filters its window
on the raw row time instead of the parsed `Trade.time`, which SDK 2.17 makes
optional. Same value, no behaviour change.

The SDK floor rises to 2.17.0, whose `Trade.time` is `datetime | None`. Upgrade the
SDK and this adapter together.

Release qualification on 2026-10-09 passed the read suites and market
consistency. Committed evidence under `release-evidence/kraken/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.17.0 publication.
