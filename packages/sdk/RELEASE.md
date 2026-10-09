# tribulnation-sdk 2.16.0

`trades_stream` takes venue settings, like `depth` and `depth_stream`, so dYdX can
stream fills from the account's full node. See ADR 0044.

New:

1. `trades_stream(..., settings: Settings = {})`, keyword-only, on `Market`,
   `Exchange`, `TradingVenue`, `TradingMarkets` and every venue market. Each venue
   reads only its own key; only dYdX reads one (`trades_source`).
2. The gateway carries it: `TradesStreamReq.settings`, sent by `ProxySDK`. Frames
   from older clients decode to `{}`, and older gateway servers ignore the field.
3. `accounts.Dydx.full_node_grpc` and `full_node_rpc`: optional, `$ENV` resolvable
   endpoints of the account's own full node, passed by `MarketSDK` to dYdX.

Compatibility: core and the gateway server pass `settings` to a venue only when it
is non-empty, so a venue package without the parameter keeps working with this core
unless a caller asks for a venue option (then `TypeError`).

This release requires dYdX 0.14.0: `MarketSDK` passes the node endpoints, which dYdX
0.13.0 rejects. Every other adapter is released alongside (Aster 0.10.0, Binance
0.7.0, Bit2Me 0.9.0, Bitget 0.11.0, Bybit 0.7.0, Coinbase 0.5.0, Deribit 0.6.0,
Hyperliquid 0.16.0, Kraken 0.7.0, KuCoin 0.6.0, Lighter 0.9.0, MEXC 2.4.0): each
accepts and ignores `settings` and requires SDK >=2.16.0. The SDK extras now require
those versions. Ethereum is unchanged.

dYdX 0.14.0 also translates `typed_core` errors by kind and releases stream
subscriptions on exit; see its `RELEASE.md`.
