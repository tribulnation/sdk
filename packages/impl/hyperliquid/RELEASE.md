# tribulnation-hyperliquid 0.18.0

Requires SDK >=2.18.0 and typed-hyperliquid >=2.6.0. Depth streams skip stale
snapshots before validating them and report how many they skipped. See ADR 0046.

Behaviour changes:

1. While every consumer of a coin and depth source keeps only the newest book (the
   default `queue_size=1, overflow='latest'`), `depth_stream` subscribes `l2Book` (and
   the fast `l2Book`) and `bbo` with typed `keep_latest`: a stale frame is decoded to
   route it but never validated nor converted. A consumer asking for more (for example
   `overflow='fail'`) reopens the shared feed unconflated, as before.
2. The yielded stream reports `skipped`, read with `tribulnation.sdk.core.skipped`:
   the books this consumer never saw, skipped upstream or in its own inbox.

Every other method is unchanged.

The SDK floor rises to 2.18.0, which adds `SkippingView` and `Subscription`'s
latest-only connector, and the typed-hyperliquid floor to 2.6.0 (typed-core 0.12
`keep_latest`). Upgrade the SDK and this adapter together.
