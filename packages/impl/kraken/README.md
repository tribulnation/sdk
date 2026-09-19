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

Spot and public linear perpetuals are available through `spot` and `perp` exchanges.
For example, `await kraken.depth('perp:PF_XBTUSD', levels=5)` reads the Futures book.
Perpetuals support discovery, tickers, rules, depth, index, statistics, historical
funding and all six trade-candle intervals. Private Futures methods, trading,
next-funding estimates and Futures streams remain unsupported.

## Identifiers

Assets are Kraken's internal ids — `XXBT`, `XETH`, `ZUSD`, `USDC`, `SOL` — the spelling
`Balance`, `Ledgers`, `TradesHistory` and `WithdrawMethods` all answer in. `Earn/Strategies`
names assets by display name (`BTC`) and is re-keyed to the same internal ids through the
venue's own `Assets` listing, which carries the same `altname` under both spellings.
Spot markets are the REST pair altname (`XBTUSD`, `ETHUSDC`): the form every `pair=` argument and
account row uses, joined internally to the WebSocket v2 symbol (`BTC/USD`) for streams.

Perpetual market IDs retain the instrument symbol (`PF_XBTUSD`, `PF_ETHUSD`).
The supported set is non-tradfi USD `flexible_futures` with unit contract size,
joined to active perpetual tickers. Kraken includes some tokenized assets in that set.

Perpetual quantities are already base units. Historical funding uses Kraken's relative
rate and maps period start to settlement time by adding one hour. Funding bounds are
inclusive; an omitted start reads all retained rows. The latest period may settle later.

## Gaps

- Spot `Market.candles`: Kraken documents a window of 720 recent candles per interval;
  BTC/ETH probes returned 721 rows including the current interval. `since` cannot
  retrieve older history, so archive backfill requires separate ingestion.
- Perpetual candles use bounded requests of 2000 possible opens, preserving aware
  half-open bounds and missing periods. Older availability depends on the market;
  the API is not a complete archive guarantee. Standard fees and maximum order size
  remain unknown. `next_funding` and Futures streams are unsupported.
- `Wallet.deposit_methods`: `DepositMethods` answers a method name per asset and no
  network field, so there is no network to report.
- `Earn`: `apr` is the midpoint of Kraken's `low`/`high` estimate and `min_qty` is never
  set, because Kraken quotes the minimum allocation in USD rather than in the asset.
