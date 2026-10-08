# tribulnation-lighter 0.5.0

Requires SDK >=2.12.0. Market, exchange and venue objects expose `account_id`,
the root SDK account key they were opened under, and build their IDs from it;
`venue_id` is the typed venue. Objects built directly keep their current IDs.
`depth()` and `depth_stream()` accept the SDK's venue-keyed `settings`.

`Book.time` is the WebSocket `order_book.last_updated_at`; REST books have no
snapshot timestamp and report `None`. Testnet deployments now report
`venue_id == 'lighter_testnet'`.

Upgrade the SDK and this adapter together.
