# Hyperliquid SDK

> Tribulnation SDK implementation for Hyperliquid.

## Installation

```bash
pip install tribulnation-hyperliquid
```

## Ticker availability

Spot and perpetual `tickers()` report actual bid/ask prices and quantities when
depth enrichment is enabled. Their `last` is `None`: asset contexts publish a
midpoint rather than a last traded price. `base_volume_24h` uses `dayBaseVlm` when
the venue supplies it and otherwise stays `None`; quote-notional `dayNtlVlm` is
never relabelled as base volume. Use `perp_stats()` for index/mark prices and
`candles()` for historical trade prices.
