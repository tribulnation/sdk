# tribulnation-binance 0.8.0

Requires SDK >=2.18.0 and typed-binance >=1.6.0. Depth streams honour the latest-only
default: stale snapshots are skipped before decoding and counted, and the USD-M
endpoints can be overridden. See ADR 0046.

New:

1. Endpoint overrides for other servers (for example local fake exchanges in stress
   tests): on USD-M futures, `rest_url`, `ws_url` (market
   streams), `public_ws_url` (book ticker and depth), `user_stream_url` and
   `ws_api_url`. `BinanceMarket.new` takes the same keywords, and the SDK
   `[accounts.<id>]` config accepts them (sdk#240). Unset, the endpoints are
   unchanged.

Behaviour changes:

1. `depth_stream` on spot and USD-M perpetuals used to ignore `queue_size` and
   `overflow` and deliver every partial-depth frame. With the default
   `queue_size=1, overflow='latest'` it now subscribes with typed `keep_latest`: a
   frame replaced before it is read is never decoded nor converted, and the yielded
   stream's `skipped` (read with `tribulnation.sdk.core.skipped`) counts it. Any other
   `queue_size`/`overflow` delivers every snapshot, unbounded, as before. Each call
   still opens its own subscription.

Every other method is unchanged.

The SDK floor rises to 2.18.0 (from 2.16.0), which adds `latest_only`, and the
typed-binance floor to 1.6.0 (typed-core 0.12 `keep_latest` and the endpoint
overrides). Upgrade the SDK and
this adapter together.

Release qualification on 2026-10-20 passed the read suites and market consistency.
Committed evidence under `release-evidence/binance/` matches pinned Catalogue
`1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release verification passes.
This adapter release follows SDK 2.18.0 publication.
