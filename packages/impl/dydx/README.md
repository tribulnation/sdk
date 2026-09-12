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
