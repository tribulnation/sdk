# tribulnation-binance 0.8.0

Requires SDK >=2.18.0 and typed-binance >=1.5.0. Depth streams honour the latest-only
default: stale snapshots are skipped before decoding and counted. See ADR 0046.

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
typed-binance floor to 1.5.0 (typed-core 0.12 `keep_latest`). Upgrade the SDK and
this adapter together.
