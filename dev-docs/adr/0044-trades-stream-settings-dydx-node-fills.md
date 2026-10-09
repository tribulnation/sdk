# ADR 0044: `trades_stream` settings and dYdX full node fills

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested with fake streams; checked live read-only
   for regular maker fills (node vs indexer vs `'fastest'`). Liquidation and deleveraging
   fills are not live-verified; not release-verified.
2. Date: 2026-10-09

## Context

The dYdX indexer pushes our fills about 1.2 s after the block time. A full node streaming
`StreamOrderbookUpdates` sees the same fills when the block is finalized, about 0.8 s after
the block time, so a hedger reacts about 0.4 s sooner. That source needs infrastructure the
caller runs (a streaming full node) and is not always available, so it must be opt-in per
stream, and a caller should be able to race it against the indexer.

`depth` and `depth_stream` already take venue-keyed `settings` to pick a venue's feed
(Hyperliquid `depth_source`). `trades_stream` took none.

## Decision

1. `trades_stream` takes `settings: Settings = {}` (keyword-only) on `Market`, `Exchange`,
   `TradingVenue` and `TradingMarkets`, in every venue market and through the gateway
   (`TradesStreamReq.settings`, empty when a client predates it). Venues read only their own
   key; all except dYdX ignore it. Core and the gateway server pass `settings` to a
   venue only when it is non-empty (`open_trades_stream`), so venue packages released
   before the parameter existed keep working with a newer core until a caller asks for
   a venue option.
2. dYdX `Settings.trades_source: 'indexer' | 'node' | 'fastest'`, default `'indexer'`
   (unchanged behaviour).
3. The node's endpoints are account configuration, not per-call settings:
   `accounts.Dydx.full_node_grpc` (`host:port`, plaintext) and `full_node_rpc` (CometBFT
   URL), both optional. They build one `typed_dydx` `Chain` client for that node, owned by
   the client alongside the public one. `'node'`/`'fastest'` without both raise
   `ValueError` on entering the stream.
4. One node subscription per client, fanned out to markets: every listed CLOB pair, the
   parent subaccount and all its children, `filter_orders_by_subaccount_id=True` (requires
   the v4-chain#3414 fix). It reconnects with backoff forever; blocks read before a
   reconnection are not re-emitted.
5. Only finalized updates (`exec_mode == 7`) produce fills. Per-fill sizes come from the
   match (`fill_amount`), prices from the maker order's subticks. Deleveraging fills, which
   the stream carries without side or price (and once per fill, each copy holding the whole
   match), take both from the block's CometBFT `match` event.
6. Node trades: `time` is `None` (the stream has no block time and the fill is never
   delayed to learn it); `details['height']` is the block height, from which a caller
   resolves the block time when it needs it; `id` is synthetic (`<height>:<subject>:<n>`);
   `fee` is `None`; `details['source'] == 'node'`. To allow this, core `Trade.time` is
   `datetime | None`: the venue's execution time, `None` when the venue doesn't report it
   on that feed. `ExchangeTrade` inherits it unchanged. History sources keep setting it.
   An earlier draft used the local receive time instead; it was misleading (fill→receive
   latency computed from it is about zero) and inconsistent with indexer fills, which
   carry the block time.
7. `'fastest'` emits each economic fill once, from the first source. Fills are keyed by
   height, indexer order id (derived from the protocol order id) and size, or for orderless
   fills by height, subaccount, CLOB pair, side and size; keys are counted as multisets and
   kept 1000 blocks. Price is not part of the key, so a rounding difference cannot double a
   fill.

## Consequences

1. Callers opting into `'node'` trade latency for the indexer's guarantees: fills during a
   node outage are missed and must be reconciled from `trades_history`; `id` differs from
   the indexer's for the same fill, and `time` is missing (resolve it from
   `details['height']`).
2. `Trade.time` becoming optional is a core contract change (minor release): consumers
   handling arbitrary venues must allow `None`. The gateway carries it as `null`; a
   gateway client on an older core cannot decode such a trade, which only a node-sourced
   dYdX stream produces.
3. `'fastest'` streams mix both trade shapes; `details['source']` tells them apart.
4. A market listed after the node subscription connected is covered from its next
   reconnection.
5. The SDK's dYdX package depends on `typed-dydx>=3.7.0` (generated
   `chain.clob.stream_orderbook_updates`) and `typed-core>=0.11.0` (gRPC status mapping);
   the latter also lets dYdX translate `BadRequest`, `AuthError` and `RateLimited` precisely.
