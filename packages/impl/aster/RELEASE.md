# tribulnation-aster 0.12.0

Requires SDK >=2.18.0 and typed-aster >=0.7.0. Depth streams skip stale snapshots
before decoding them and report how many they skipped, and the perpetual endpoints
can be overridden. See ADR 0046.

New:

1. Endpoint overrides for other servers (for example local fake exchanges in stress
   tests): `rest_url` (futures REST, including `/fapi/v3`),
   `ws_url` (futures market streams) and `user_stream_url` (futures user data); spot
   keeps its endpoints. `AsterMarket.new` takes the same keywords, and the SDK
   `[accounts.<id>]` config accepts them (sdk#240). Unset, the endpoints are
   unchanged.

Behaviour changes:

1. While every consumer of a symbol and depth source keeps only the newest book (the
   default `queue_size=1, overflow='latest'`), `depth_stream` subscribes partial depth
   (`'depth'`, `'fast'`) and `bookTicker` (`'bbo'`) with typed `keep_latest`, on spot
   and perpetuals: a stale frame is never decoded nor converted into a `Book`. A
   consumer asking for more (for example `overflow='fail'`) reopens the shared feed
   unconflated, as before.
2. The yielded stream reports `skipped`, read with `tribulnation.sdk.core.skipped`:
   the books this consumer never saw, skipped upstream or in its own inbox.

Every other method is unchanged.

The SDK floor rises to 2.18.0, which adds `SkippingView` and `Subscription`'s
latest-only connector, and the typed-aster floor to 0.7.0 (typed-core 0.12
`keep_latest` and the endpoint overrides). Upgrade the SDK and this adapter together.
