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

Mainnet only for Spot, which has no testnet; `kraken_testnet` is the Futures demo
environment (perpetuals only). `validate` toggles pydantic validation of API responses.
A public `accounts.Kraken(public=True)` account is read-only: market data works without
credentials. Spot balances, orders, open orders and fills need a Spot API key
(`api_key`/`private_key`); perpetual account reads and orders need the separate Futures
API key (`futures_api_key`/`futures_private_key`). One account can hold both.

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

  | SDK market ID | REST `pair=` (altname) | `AssetPairs` key | WebSocket v2 symbol |
  |---|---|---|---|
  | `kraken:spot:XBTUSD` | `XBTUSD` | `XXBTZUSD` | `BTC/USD` |
  | `kraken:spot:KAVAUSD` | `KAVAUSD` | `KAVAUSD` | `KAVA/USD` |

- Spot `rules()` returns `SpotRules`: `base`/`quote` and `fee_asset` use Kraken's
  internal asset IDs (`XXBT`, `KAVA`, `ZUSD`), the same form balances, ledgers and
  withdrawal methods answer in.
- Spot collateral IDs are `<account>:spot:<internal asset id>`: `kraken:spot:ZUSD`,
  `kraken:spot:KAVA`. The Spot wallet and the Futures multi-collateral pool
  (`kraken:perp`) are separate money (ADR 0051).
- Spot `Exchange.markets()` returns every altname in `AssetPairs`, whatever its status.
  Perpetual discovery applies the active-product filter described above.

## Venue-specific semantics

- Perpetuals serve public depth, tickers, rules, index, mark/open-interest statistics,
  funding history and candles without a key; with the Futures key they also trade
  (`lmt`, `post`, `ioc`, batches, in-place edits) and read positions, the
  multi-collateral pool, leverage, fees, fills and funding payments.
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
- Spot orders are REST limit orders: `LIMIT` is GTC, `POST_ONLY` adds the `post` flag,
  `MARKET` is an IOC limit at `price`. `settings={'kraken': {'time_in_force': 'ioc'}}`
  (or `'post'`) sends a `LIMIT` that way; `reduce_only` raises `ValueError` on Spot.
  Every Spot order asks for fees in the quote asset (`fciq`), so a fill moves exactly
  its quantity of base. `AddOrder` reports no execution: `filled_qty` is `None`, and
  `query_order` reads `QueryOrders`, which also answers closed orders. Kraken's `EOrder`
  errors and bad requests raise `OrderRejected`; service and internal errors stay
  ambiguous `ApiError`s.
- Spot `replace_order` amends in place (`AmendOrder`): the txid stays and queue priority
  is kept where Kraken can. Kraken amends the total quantity, so the SDK reads the
  filled part with `QueryOrders` first. A replacement on the other side cancels and
  places. `cancel_order` raises `OrderNotFound` for an order Kraken no longer knows.
  `cancel_open_orders` cancels this pair's open orders one by one, never the
  account-wide `CancelAll`.
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
- Spot REST `depth` serves at most 500 levels per side; a larger `levels` asks for 500,
  since Kraken answers a larger `count` with its 100-level default.
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
- Spot `balances()` and `SpotExchange.balance(asset)` read `BalanceEx`: `total` is
  `balance`, `free` is `balance - hold_trade`. Assets allocated to Earn (`.F`, `.B`,
  `.S` ids) are not counted. One answer is shared per `ttl` across the account's markets
  and collateral IDs, since Kraken meters private REST calls per key (a counter decaying
  0.33 to 1 point a second, by verification tier); orders and cancels spend the separate
  per-pair trading counter instead.

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
