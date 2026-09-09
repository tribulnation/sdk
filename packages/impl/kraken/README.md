# Kraken SDK

> Tribulnation SDK implementation for Kraken.

## Installation

```bash
pip install tribulnation-kraken
```

## Surfaces

| Surface | Class | Credentials |
|---|---|---|
| Earn | `tribulnation.kraken.Earn` | keyed — `Earn/Strategies` needs an API key |
| Market | `tribulnation.kraken.KrakenMarket` | public for market data, keyed for balances, orders and fills |
| Report | `tribulnation.kraken.Report` | keyed |
| Wallet | `tribulnation.kraken.Wallet` | keyed |

```python
from tribulnation.kraken import KrakenMarket

async with KrakenMarket.new(public=True) as kraken:
  book = await kraken.depth('spot:XBTUSD', levels=5)
  print(book.best_bid, book.best_ask)
```

Spot only, read only. Kraken Futures is a separate product with its own API keys and
`typed_kraken` does not wrap it; `place_order`/`cancel_order` raise `NotImplementedError`
because we do not trade on Kraken.

## Identifiers

Assets are Kraken's internal ids — `XXBT`, `XETH`, `ZUSD`, `USDC`, `SOL` — the spelling
`Balance`, `Ledgers`, `TradesHistory` and `WithdrawMethods` all answer in. `Earn/Strategies`
names assets by display name (`BTC`) and is re-keyed to the same internal ids through the
venue's own `Assets` listing, which carries the same `altname` under both spellings.
Markets are the REST pair altname (`XBTUSD`, `ETHUSDC`): the form every `pair=` argument and
account row uses, joined internally to the WebSocket v2 symbol (`BTC/USD`) for streams.

## Gaps

- `Market.candles`: Kraken's OHLC endpoint serves only the 720 most recent candles per
  interval, whatever `since` says, so there is no walk to older history.
- `Wallet.deposit_methods`: `DepositMethods` answers a method name per asset and no
  network field, so there is no network to report.
- `Earn`: `apr` is the midpoint of Kraken's `low`/`high` estimate and `min_qty` is never
  set, because Kraken quotes the minimum allocation in USD rather than in the asset.
