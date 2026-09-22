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

## Exchange history

Use `exchange.trades_history(None, start, end)` for every market in a spot or
perpetual exchange, and `perp_exchange.funding_payments(None, start, end)` for its
funding payments. Each returned record carries `market_id`. Native account pages
are fetched once per call and filtered to the selected exchange, including its
builder DEX when applicable. Passing a market ID retains the single-market API.

Trade history uses `userFillsByTime`, subject to its 10,000-fill retention limit;
TWAP slice fills require a separate endpoint and are not included. Spot history
requires current metadata to resolve canonical market IDs and raises if a
historical spot pair cannot be resolved. Funding amounts follow the SDK convention:
positive means paid, negative means received. This also corrects the previous
reversed sign in the single-market funding mapper.
