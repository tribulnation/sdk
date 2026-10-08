# tribulnation-hyperliquid 0.12.0

Requires SDK >=2.12.0. Market, exchange and venue objects expose `account_id`,
the root SDK account key they were opened under, and build their IDs from it;
`venue_id` is the typed venue. Objects built directly keep their current IDs.
`depth()` and `depth_stream()` accept the SDK's venue-keyed `settings`.

Depth reads take `settings={'hyperliquid': {'depth_source': ...}}`:

1. `'l2'` (default): `l2Book`, 20 levels per side, about every 5.4 s.
2. `'fast'`: `l2Book` with `fast=True`, 5 levels per side, about every 0.5 s, on
   a dedicated WebSocket connection, so `'fast'` and `'l2'` can run together.
3. `'bbo'`: the `bbo` channel, top of book with sizes, pushed on change.

Subscriptions are shared per coin and source. REST has no faster endpoint: every
source reads the `l2Book` snapshot, trimmed to its level count. `levels` now
trims books on REST and WebSocket (it was ignored) and never selects the source.
`Book.time` is the `l2Book`/`bbo` block time on perps, spot and builder dexes,
including top-of-book tickers. Testnet objects now report
`venue_id == 'hyperliquid_testnet'`.

Upgrade the SDK and this adapter together.
