# tribulnation-dydx 0.14.0

Requires SDK >=2.16.0, typed-dydx >=3.7.0 and typed-core >=0.11.0. `trades_stream`
can take fills from the account's own full node, ahead of the indexer. See ADR 0044
and "Fill sources" in the dYdX docs.

New:

1. `trades_stream(settings={'dydx': {'trades_source': ...}})`, one of `'indexer'`
   (default, unchanged), `'node'` or `'fastest'`.
   - `'node'`: fills come only from the full node's `StreamOrderbookUpdates`
     (finalized blocks only). Fills of our orders and our liquidations come from the
     stream at the maker's price; a deleveraging fill takes its side and price from
     the block's CometBFT `match` event (`block_results`). Fills during a node outage
     are missed: reconcile with `trades_history`.
   - `'fastest'`: node and indexer race, and each fill is emitted once, by the first
     source to deliver it (`details['source']`). The indexer keeps delivering while
     the node is down.
2. Node endpoints are account configuration: `accounts.Dydx.full_node_grpc`
   (`'host:port'`, plaintext gRPC streaming) and `full_node_rpc` (CometBFT RPC URL),
   both optional and `$ENV` resolvable, also `DydxMarket.new(full_node_grpc=...,
   full_node_rpc=...)`. `'node'` and `'fastest'` without both raise `ValueError` when
   the stream is entered. One node subscription per client serves every market; it
   reconnects with backoff and never re-emits a block it already read. The node must
   carry the v4-chain#3414 fix (`filter_orders_by_subaccount_id`).
3. Node trades: `time` is the local receive time, `id` is synthetic
   (`<height>:<subject>:<n>`), `order_id` is `None` for liquidated, deleveraged and
   offsetting fills, and `fee` is `None`.

Behaviour changes:

1. `typed_core` `BadRequest`, `AuthError`, `RateLimited` and `LogicError` now raise
   the matching SDK classes instead of `ApiError` or `Error`. gRPC failures are
   translated by status through `typed-core` 0.11 (the grpcio `_InactiveRpcError`
   path is removed), including the fee-holiday query.
2. Fix: leaving a `trades_stream` context released its subscription only when the
   garbage collector ran. It is now released on exit, for the indexer path too.

Verified live, read-only, on 7 markets for 15 minutes: node and indexer agreed
exactly on all 3 fills (order id, price, signed size, maker), the node delivering
0.33–0.58 s earlier. Liquidation and deleveraging fills are covered by unit fixtures
only.

`MarketSDK` in SDK 2.16.0 passes the node endpoints to this package, so SDK 2.16.0
requires dYdX 0.14.0 and this release requires SDK 2.16.0: upgrade them together.
