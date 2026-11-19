<p align="center">
  <a href="https://tribulnation.com/sdk/docs/market/implementations/kraken">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://tribulnation.com/media/lockups/kraken-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://tribulnation.com/media/lockups/kraken-light.svg">
      <img alt="Tribulnation SDK Kraken" src="https://tribulnation.com/media/lockups/kraken-light.svg" width="520">
    </picture>
  </a>
</p>

<p align="center">
  <em>Tribulnation SDK implementation for Kraken.</em>
</p>

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

Spot and linear perpetuals are available through `spot` and `perp` exchanges.
For example, `await kraken.depth('perp:PF_XBTUSD', levels=5)` reads the Futures book.
Perpetuals serve public data without a key; with a Futures API key (separate from Spot
keys: `futures_api_key`/`futures_private_key`, or `KRAKEN_FUTURES_API_KEY`/
`KRAKEN_FUTURES_PRIVATE_KEY`) they also trade: orders (`lmt`, `post`, `ioc`, batches,
in-place edits), positions, the multi-collateral pool, leverage, fees, own fills and
funding payments, and the WebSocket book and fills feeds.

```python
async with KrakenMarket.new(futures_api_key=..., futures_private_key=...) as kraken:
  market = await kraken.perp_market('perp:PF_POPCATUSD')
  order = await market.place_order(
    {'type': 'POST_ONLY', 'qty': -1000, 'price': '0.0280'}
  )
```

Spot trades with the Spot API key (`api_key`/`private_key`, or `KRAKEN_API_KEY`/
`KRAKEN_PRIVATE_KEY`): REST limit orders (`LIMIT` GTC, `POST_ONLY` with the `post` flag,
`MARKET` as an IOC limit at `price`), in-place amends, cancels, open and queried
orders, `balances()` and the Spot collateral IDs (`kraken:spot:ZUSD`), and the
`executions` fills stream. Spot and perpetuals can share one account with both key pairs,
for a Spot/perpetual carry on Kraken:

```python
async with KrakenMarket.new(
  api_key=..., private_key=..., futures_api_key=..., futures_private_key=...
) as kraken:
  spot = await kraken.spot_market('spot:KAVAUSD')
  await spot.place_order({'type': 'POST_ONLY', 'qty': 500, 'price': '0.0790'})
  print(await spot.balances(), await spot.collateral_ids())
```

The `kraken_testnet` venue is the Futures demo environment (perpetuals only). Spot has
no testnet.

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
  remain unknown.
- Perpetual `trades_history` reads REST `fills`, which carry no fee; `trades_stream`
  fills carry theirs. Isolated-margin buckets (`perp_collateral` of a market with a
  leverage preference) are not supported.
- `Wallet.deposit_methods`: `DepositMethods` answers a method name per asset and no
  network field, so there is no network to report.
- `Earn`: `apr` is the midpoint of Kraken's `low`/`high` estimate and `min_qty` is never
  set, because Kraken quotes the minimum allocation in USD rather than in the asset.
