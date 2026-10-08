# tribulnation-aster 0.6.0

Requires SDK >=2.12.0. Market, exchange and venue objects expose `account_id`,
the root SDK account key they were opened under, and build their IDs from it;
`venue_id` is the typed venue. Objects built directly keep their current IDs.
`depth()` and `depth_stream()` accept the SDK's venue-keyed `settings`.

`Book.time` is Aster's transaction time `T`, on REST and WebSocket, spot and
perpetuals.

Upgrade the SDK and this adapter together.
