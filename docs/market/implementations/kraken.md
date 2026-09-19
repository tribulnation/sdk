<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Kraken Market

> Spot and public linear perpetual market data. `tribulnation-kraken`, venue name `kraken`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Kraken-specific.

## Account

Mainnet only, no testnet. `validate` toggles pydantic validation of API responses. The
built-in `kraken` account is `accounts.Kraken(public=True)`, read-only: market data works
without credentials; Spot balances, open orders, fills and the fills stream need an API key. Private
Futures operations are unsupported. Public perpetual support requires
`tribulnation-kraken >=0.3.0` (with `typed-kraken >=0.4.0`).

## Exchange & ID conventions

- Exchanges are `spot` and `perp`. The perpetual exchange serves active non-tradfi
  USD linear contracts with unit contract size, including tokenized assets classified
  that way by Kraken. Inverse, dated and expired products are excluded.
- Perpetual IDs are native instrument symbols: `kraken:perp:PF_XBTUSD` and
  `kraken:perp:PF_ETHUSD`. Public Futures reads need no API keys.
- Spot market IDs are Kraken's REST pair altnames, e.g. `XBTUSD`, `ETHUSDC` — the spelling
  every `pair=` argument and every account row (`TradesHistory`, `OpenOrders`) uses.
  The venue also names the same pair `XXBTZUSD` (the `AssetPairs` key) and `BTC/USD`
  (the WebSocket v2 symbol); both are looked up internally and never exposed.
- Full SDK ID: `kraken:spot:XBTUSD` (or `<your-account-key>:spot:XBTUSD`).
- `Rules.fee_asset` uses Kraken's internal asset ID (e.g. `ZUSD`), the same form
  balances, ledgers and withdrawal methods answer in. Base/quote identities come
  from the Catalogue instrument.
- Spot `Exchange.markets()` returns every altname in `AssetPairs`, whatever its status.
  Perpetual discovery applies the active-product filter described above.

## Venue-specific semantics

- Perpetuals support REST depth, tickers, rules, index, mark/open-interest statistics,
  funding history and candles. `next_funding`, Futures streams and private Futures
  account/trading methods are explicitly unsupported.
- Perpetual book sizes, ticker sizes, volume and open interest are already base units.
  Rules use the native price tick and `10 ** -contractValueTradePrecision` quantity
  step. USD fees resolve to `ZUSD`; standard rates and maximum order size are unknown.
- Perpetual `funding_rates` preserves the published relative rate. Its SDK payment
  timestamp is the native accrual-period start **plus one hour**, Kraken's documented
  settlement boundary. Bounds are inclusive and apply after conversion. An omitted
  start includes all retained rows; the latest row can settle in the future.
- Perpetual trade candles support all six intervals through bounded 2000-open Charts
  windows. Bounds are aware and half-open; missing intervals are not filled. History
  depends on availability for the market and is not a complete archive guarantee.
- `place_order`/`cancel_order` raise `NotImplementedError`: we do not trade on Kraken.
- Spot `candles` supports `1m`, `5m`, `15m`, `1h`, `4h`, `1d` through validated OHLC rows.
  Bounds must be timezone-aware and half-open (`start <= open < end`). The SDK
  preserves native order, removes duplicate opens, and includes the forming candle
  when its open is in range. Equal bounds return no rows; invalid bounds fail locally.
  Kraken documents a retained window of 720 recent rows per interval; `since` cannot
  retrieve older history. BTC/ETH probes returned 721 rows including the current
  interval. Older ranges can therefore return empty or partial data.
  Archive files require separate ingestion; this method does not provide archive backfill.
- Spot `depth_stream` subscribes at the smallest of Kraken's fixed book depths (10, 25, 100,
  500, 1000) holding `levels`, folds the channel's snapshot-then-updates into whole
  books, and trims each to `levels`. Subscriptions are shared per symbol and depth.
- Spot `rules()` reads `AssetPairs`: `tick_size` and the `lot_decimals` step, `ordermin` as
  the minimum quantity and `costmin` as the minimum cost; Kraken publishes no price
  bounds. Fees are the base tier of the pair's own schedule, in the quote asset — and
  `None` when rates are absent. `fees()` separately reads the account's `TradeVolume` schedule.
- Spot `tickers()` is one `Ticker` request for the whole catalogue, re-keyed by altname;
  `bid_qty`/`ask_qty` are the lot volumes at the best bid and ask.
- `open_orders()` filters the account-wide `OpenOrders` on the order description's pair.
- `trades_history()` pages `TradesHistory` newest first, 100 per page; `fee` is in the
  quote asset, which is where Kraken denominates it.
- `trades_stream()` is the account-wide `executions` channel filtered to fills
  (`exec_type == 'trade'`) on this market's symbol.
- `position` is the base asset's balance, held amounts included. `collateral` reports the
  quote asset's balance: `equity = balance`, `free_collateral = balance - hold_trade`,
  and `available_notional` is that free balance. Balances are cached for one second
  across the three, since Kraken meters private calls per account.

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()

sdk = MarketSDK({'kraken_account1': accounts.Kraken()})

book = await sdk.depth('kraken_account1:spot:XBTUSD', levels=5)
async with sdk.depth_stream('kraken:spot:XBTUSD', levels=10) as books:
  async for book in books:
    print(book.best_bid, book.best_ask)
    break
```

Public perpetual reads use the built-in public account:

```python
from tribulnation.kraken import KrakenMarket

async with KrakenMarket.new(public=True) as kraken:
    book = await kraken.depth('perp:PF_XBTUSD', levels=5)
    print(book.best_bid, book.best_ask)
```

<!-- next -->

---

← [Bitget Market](bitget.md) · **Next:** [Coinbase Market](coinbase.md) →

<!-- /next -->
