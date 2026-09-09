# Binance SDK

> Tribulnation SDK implementation for Binance.

## Installation

```bash
pip install tribulnation-binance
```

## Public market data

`BinanceMarket.new(public=True)` discovers `spot` and `usdm`. Both serve candles
and tickers; `usdm` also serves funding history, next funding and `perp_stats`.
Its bulk snapshots include actively trading perpetuals, not dated futures.
Perp stats combine bulk pricing/funding with a public open-interest request per
market, limited to five concurrent requests. These are separate observations,
not an atomic snapshot. No futures account credentials are required.

## Reporting

Reporting is explicitly spot-side: snapshots contain Spot, Funding and Simple Earn
balances; history contains spot fills, deposits/withdrawals and Spot ↔ Funding
transfers. Futures, margin, options and Portfolio Margin are not inspected or
represented as zero balances. No Futures permission or scope configuration is needed.
Failures on supported reads propagate instead of becoming empty results.
The underlying Typed futures APIs and existing public futures market data are unchanged.

`Reporting.history(start=None, end=None)` accepts omitted bounds. `end` defaults
to UTC now. When `start` is omitted, deposits/withdrawals start 90 days before
`end` and Spot/Funding transfers six calendar months before it. These are default query horizons, not completeness
guarantees; explicit bounds are preserved and split into legal endpoint windows.

Spot fill history discovers and sweeps the venue's published spot symbols.
No `spot_markets` or `usdm_markets` configuration is required or accepted. Spot
fills walk retained trade ids, filtering any supplied time bounds locally.
Discovery does not use current balances or open positions, so closing a position
does not remove its market from the sweep. A full sweep can require many requests.

API history is best-effort. Delisted symbols absent from discovery, venue retention
and records beyond an inseparable endpoint cap may leave gaps for file ingestion.
