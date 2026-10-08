# tribulnation-aster 0.6.0

Requires SDK >=2.12.0. Market, exchange and venue objects expose `account_id`,
the root SDK account key they were opened under, and build their IDs from it;
`venue_id` is the typed venue. Objects built directly keep their current IDs.
`depth()` and `depth_stream()` accept the SDK's venue-keyed `settings`.

`Book.time` is Aster's transaction time `T`, on REST and WebSocket, spot and
perpetuals.

Upgrade the SDK and this adapter together.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/aster/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.12.0 publication.
