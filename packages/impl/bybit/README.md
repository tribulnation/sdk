# Bybit SDK

> Tribulnation SDK implementation for Bybit.

## Installation

```bash
pip install tribulnation-bybit
```

## Surfaces

| Surface | Class | Credentials |
|---|---|---|
| Market | `tribulnation.bybit.BybitMarket` | keyed (pass `public=True` for market data only) |
| Earn | `tribulnation.bybit.Earn` | keyed, though every catalogue endpoint is public |
| Wallet | `tribulnation.bybit.Wallet` | keyed |
| Report | `tribulnation.bybit.Report` | keyed |

```python
from tribulnation.bybit import BybitMarket

async with BybitMarket.new() as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTCUSDT')
  print(await market.next_funding())
```

Credentials come from `BYBIT_API_KEY`/`BYBIT_API_SECRET` when not passed.

## Exchanges

Bybit v5 is one API discriminated by a `category` parameter rather than separate spot and
futures endpoints, so `spot` and `perp` share a single connection, instrument cache and
private stream.

`perp` lists linear perpetuals only. Bybit's `linear` category also carries 40-odd dated
futures, which settle on a delivery date and pay no funding — nothing about the
`PerpMarket` contract describes them.

## Regions

Bybit's regional entities are separate accounts with separate keys, separate environment
variables and different product universes; `bybit.eu` in particular lists no derivatives
at all. Pick one at construction:

```python
BybitMarket.new(region='eu')  # reads BYBIT_EU_API_KEY / BYBIT_EU_API_SECRET
```

## History windows

Bybit caps how wide a single history query may be and rejects a wider one rather than
truncating it — 7 days for trade history and the transaction log, 30 for deposit and
withdrawal records — and refuses any window starting more than two years back. Both
`Market.trades_history()` and `Report.history()` take whatever window you give them and
split it to fit; `Report.history()` with no window sweeps the full two years.
