# tribulnation-sdk 2.17.0

Placement responses report what filled, `Trade.time` becomes optional, and Aster gets
its own settings key. See ADR 0044 for `Trade.time`.

New:

1. `OrderResponse.filled_qty: Decimal | None = None`: the unsigned base quantity the
   venue's placement response reports filled. Final only for immediate orders (IOC or
   `MARKET`); for a resting order it is what filled on arrival. `None` where the venue
   answers before matching: accepting an order is not executing it. This release:
   Hyperliquid 0.17.0 (`filled.totalSz`) and Aster 0.11.0 perpetuals (`executedQty`);
   every other venue reports `None`. The field has a default, so existing
   constructors keep working, and the gateway carries it.
2. `Settings` gains the `aster` key (`tribulnation.aster.market.settings.Settings`):
   `time_in_force: 'IOC'` for `LIMIT` orders and `depth_source` (`'depth'`, `'fast'`,
   `'bbo'`). Lighter's settings gain `time_in_force: 'immediate-or-cancel'` and
   `depth_source` (`'order_book'`, `'bbo'`). See the Aster and Lighter release notes.
3. `Book.time` docs distinguish snapshot feeds (the time the snapshot was current)
   from incremental and on-change feeds (the latest exchange event reflected). No
   code change.

Behaviour changes:

1. `Trade.time` is `datetime | None`: the venue's execution time, `None` when the
   venue doesn't report it on that feed. Only dYdX full-node fills (dYdX 0.15.0,
   `trades_source` `'node'` or `'fastest'`) are `None`; `trades_history` always sets
   it. Consumers handling arbitrary venues must allow `None`. The gateway carries it
   as `null`; a `ProxySDK` client older than 2.17.0 cannot decode such a trade, so
   upgrade clients with or before gateways.

This release requires Aster 0.11.0, dYdX 0.15.0, Hyperliquid 0.17.0, Kraken 0.7.1 and
Lighter 0.10.0, which require SDK >=2.17.0; the SDK extras now require those versions.
Upgrade the SDK and those adapters together. Other adapters are unaffected.

`filled_qty` and the IOC settings are verified by unit fixtures only; no live trading
run covers them, and the read suites place no orders.
