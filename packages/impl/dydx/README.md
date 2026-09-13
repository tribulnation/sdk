# dYdX SDK

> Tribulnation SDK implementation for dYdX.

## Installation

```bash
pip install tribulnation-dydx
```

## Ticker availability

`tickers()` reports actual bid/ask prices and quantities when depth enrichment is
enabled. Its `last` is `None`: the market catalogue only publishes an oracle price,
which is not the last traded price. `base_volume_24h` is also `None` because the
catalogue's `volume24H` is quote-denominated turnover. No approximate conversion or
per-market trade-history sweep is performed. Use `perp_stats().index` for the oracle
price and `candles()` for historical trade prices and base volumes.

## Reporting cost basis

`Report.snapshot()` returns the native `Snapshots.snapshot()` record. Each perpetual
subaccount pairs collateral (`equity - unrealizedPnl`) with the venue's signed sizes
and entry prices from the same indexer response. At the corresponding marks,
collateral plus `sum(size * (mark - entry_price))` preserves venue equity. Snapshot
reads do not fetch or replay fills, so fill coverage and fill/snapshot timing
mismatches cannot introduce a separate cash adjustment.

History still replays chronological fills using average-cost accounting to compute
realized P&L, retaining the remaining entry basis on partial closes and resetting it
on position flips. This reconstructed basis can differ from the venue's snapshot
basis. Consumers must not assume that history's realized P&L and snapshot cash share
one reconstructed basis. Any reconciliation must adjust both collateral and position
entry prices consistently and first establish matching holdings and capture times.

Version 0.7.1 restores native snapshot delegation to fix the equity distortion in
0.7.0 ([issue #39](https://github.com/tribulnation/sdk/issues/39)). This correction
applies to newly fetched snapshots; downstream dependency rollout and correction of
stored snapshots are separate work.
