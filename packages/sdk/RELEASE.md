# tribulnation-sdk 2.18.0

Book streams skip stale snapshots before decoding them and report how many they
skipped, books and rules can be rescaled to asset units, accounts can point venues at
other endpoints, and the gateway moves to msgspec with a negotiated protocol version.
See ADR 0046.

New:

1. `Book.scaled(m)` and `Rules.scaled(m)` return a book or rules in asset units for a
   contract of `m` units of its asset (Hyperliquid `kPEPE` is 1000 PEPE): prices are
   divided by `m`, quantities multiplied by it, notionals unchanged. `Rules`
   rescales `tick_size`, `fixed_min_price`/`fixed_max_price` (divided) and
   `step_size`, `fixed_min_qty`, `max_qty` (multiplied); `min_value`, relative price
   bounds, fees, `api` and `details` are unchanged. Both return new objects and raise
   `ValueError` for a non-positive `m`.
2. `tribulnation.sdk.core` adds `latest_only(queue_size, overflow)`, the `Skipping`
   protocol, `SkippingView` and `skipped(stream)`. `Subscription` takes an optional
   `subscribe_latest` connector, opened while every subscriber is latest-only
   (`queue_size=1, overflow='latest'`); a subscriber that wants every item reopens
   the upstream unconflated. `StreamInbox.skipped` counts `'latest'` drops plus
   upstream skips credited while subscribed. `skipped(stream)` returns that count, or
   `None` for streams that do not count.
3. Account configs take optional venue endpoint fields, passed to the typed clients
   (for example to run against local fake exchanges in stress tests; sdk#240). Aster:
   `rest_url`, `ws_url`, `user_stream_url` (perpetuals). Binance USD-M: `rest_url`,
   `ws_url`, `public_ws_url`, `user_stream_url`, `ws_api_url`. Hyperliquid and
   Lighter: `rest_url`, `ws_url`. dYdX: `indexer_rest_url`, `indexer_ws_url`, and
   `validator_grpc` with `validator_rpc`, set together. Every field accepts
   `$ENV_VAR`; unset fields keep today's endpoints.

Behaviour changes:

1. With the default `queue_size=1, overflow='latest'`, Binance spot and USD-M partial
   depth, Aster partial depth and `bookTicker`, and Hyperliquid `l2Book` and `bbo`
   subscribe their typed client with `keep_latest`: stale frames are neither decoded
   nor turned into books (ADR 0046, sdk#230). Binance depth streams now honour the
   latest-only default; other `queue_size`/`overflow` values deliver every frame, as
   before. Diffs, trades, fills and account events are never conflated.
2. Gateway: wire messages are msgspec Structs instead of pydantic TypeAdapters. Frames
   stay JSON and old and new peers interoperate; durations are now written in seconds
   (`PT28800S`), which both codecs read. The upgrade negotiates the
   `tribulnation-gateway.v1` subprotocol: a client offering only another version is
   refused with 400, and `ProxySDK` raises `GatewayError` on a refused handshake or a
   foreign protocol. Peers naming no subprotocol (SDK 2.17 and earlier) are treated as
   v1. `docs/gateway-protocol.md` specifies the protocol, with a generated JSON
   Schema. The `gateway` extra installs msgspec instead of pydantic. Gateway-proxied
   streams report only the proxy-side inbox's skips.

This release goes with Aster 0.12.0, Binance 0.8.0 and Hyperliquid 0.18.0, which
import `latest_only`/`SkippingView` and require SDK >=2.18.0, dYdX 0.17.0 (absolute
order expiry settings; still SDK >=2.17.0) and Lighter 0.11.0 (endpoint overrides;
still SDK >=2.17.0). All five accept the endpoint fields. The SDK extras now require
those versions. Upgrade the SDK and those adapters together; older adapters keep
working with this core, without conflation or endpoint overrides. Other adapters are
unaffected.

Conflation is verified by unit tests and a local synthetic burst benchmark; the read
suites exercise these depth streams live but do not measure skipping. The endpoint
fields are verified by unit tests; the read suites use the default endpoints.

Qualification on 2026-10-20, against the unchanged Catalogue pin
`1851660ac2bed8243dd9ce9c7297fe05c7130973`: all 14 venues have passing, verified
read-suite evidence, and every market venue passing consistency evidence. The recorded
pins move to typed-core 0.12.0, typed-binance 1.6.0, typed-aster 0.7.0,
typed-lighter 0.3.0 and typed-hyperliquid 2.6.0.

All 2,115 repository unit tests pass.
