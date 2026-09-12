# MEXC SDK

> Tribulnation SDK implementation for MEXC.

## Installation

```bash
pip install tribulnation-mexc
```

## Market

Spot supports the existing trading and account surfaces. The `perp` exchange adds
public linear perpetual discovery, tickers, order-book snapshots, candles, index
prices, next funding, funding-rate history and `perp_stats`. Native symbols such as
`BTC_USDT` are preserved. Perpetual streams, rules and private/trading methods remain
unimplemented; discovering public futures does not enable futures account access.

Volumes and open interest are converted from contracts to base units with the
contract's `contractSize`. Bulk `perp_stats` does not invent a funding interval or
settlement timestamp missing from the ticker response: use `next_funding()` for
that contract's current settlement state. Candles use required aware `[start, end)`
bounds and segmented windows of at most 2000 opens, retaining native order and gaps.

Bulk perpetual snapshots reject unknown requested market IDs and fail visibly when
the response omits a selected contract (or any discovered contract when requesting
all markets). An explicit empty selection returns an empty mapping without requests.

## Report

`Report` covers `snapshot()` (spot balances, futures assets and open positions) and
`history()` (spot fills across automatically discovered markets, crypto deposits and
withdrawals, futures funding settlements). The API key needs MEXC's spot trade-read,
wallet-read and futures-read scopes. See
[docs/report/implementations/mexc.md](../../../docs/report/implementations/mexc.md).
