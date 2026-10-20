# tribulnation-dydx 0.17.0

Requires SDK >=2.17.0, typed-dydx >=3.7.0 and typed-core >=0.11.0, unchanged. Orders
can carry an absolute expiry, so placing one needs no chain-tip read, and the
endpoints can be overridden. See "Order expiry" in the dYdX docs.

New:

1. Two optional `settings['dydx']` keys: `good_til_block` (`int`, short-term orders)
   and `good_til_block_time` (timezone-aware `datetime`, long-term and conditional
   orders, whole seconds). When set, `place_order` sends the value as is and neither
   the SDK nor typed-dydx reads the latest block; the chain validates the window (a
   height already past, or more than 20 blocks ahead, is refused).
2. An absolute setting together with its delta counterpart (`short_term_gtb`,
   `long_term_gtbt`), or on the wrong order kind, raises `ValueError` before anything
   is sent. Unset, behaviour is unchanged. Cancellations still read the latest block.
3. Endpoint overrides for other servers (for example local fake exchanges in stress
   tests): `indexer_rest_url`, `indexer_ws_url`, and `validator_grpc` (plaintext
   `host:port`) with `validator_rpc` (CometBFT URL), which must be set together and
   then carry chain queries and order broadcasts. `DydxMarket.new` takes the same
   keywords, and the SDK `[accounts.<id>]` config accepts them (sdk#240). Unset, the
   endpoints are unchanged.

The dYdX docs' Settings table listed keys `Settings` rejects (`order_flags`,
`limit_tif`, `market_tif`); it now lists the real keys (`flags`, `tif`, ...).

Every other method is unchanged. The expiry settings are verified by unit fixtures
only; the read suites place no orders.
