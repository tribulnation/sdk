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

> Spot only, read only. `tribulnation-kraken`, venue name `kraken`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Kraken-specific.

## Account

Mainnet only, no testnet. `validate` toggles pydantic validation of API responses. The
built-in `kraken` account is `accounts.Kraken(public=True)`, read-only: market data works
without credentials; balances, open orders, fills and the fills stream need an API key.

## Exchange & ID conventions

- The only exchange is `spot` (`exchange_id == 'spot'`); any other exchange ID raises.
  Kraken Futures is a separate product on its own host with its own API keys, and
  `typed_kraken` does not wrap it.
- Market IDs are Kraken's REST pair altnames, e.g. `XBTUSD`, `ETHUSDC` — the spelling
  every `pair=` argument and every account row (`TradesHistory`, `OpenOrders`) uses.
  The venue also names the same pair `XXBTZUSD` (the `AssetPairs` key) and `BTC/USD`
  (the WebSocket v2 symbol); both are looked up internally and never exposed.
- Full SDK ID: `kraken:spot:XBTUSD` (or `<your-account-key>:spot:XBTUSD`).
- `Rules.base`/`quote` are Kraken's internal asset ids (`XXBT`, `ZUSD`), the same form
  balances, ledgers and withdrawal methods answer in.
- `Exchange.markets()` returns every altname in `AssetPairs`, whatever its status.

## Venue-specific semantics

- Spot only — there is no `PerpMarket`/`PerpExchange`, so `perp_exchange`, `index`,
  `next_funding`, `funding_*`, and `perp_position` are unsupported for this venue.
- `place_order`/`cancel_order` raise `NotImplementedError`: we do not trade on Kraken.
- `candles` raises `NotImplementedError`: Kraken's OHLC endpoint serves only the 720
  most recent candles per interval, whatever `since` says, so there is no walk to older
  history, and `typed_kraken`'s `OhlcResult` declares the polling cursor but not the
  candle rows. `CANDLE_INTERVALS` is empty.
- `depth_stream` subscribes at the smallest of Kraken's fixed book depths (10, 25, 100,
  500, 1000) holding `levels`, folds the channel's snapshot-then-updates into whole
  books, and trims each to `levels`. Subscriptions are shared per symbol and depth.
- `rules()` reads `AssetPairs`: `tick_size` and the `lot_decimals` step, `ordermin` as
  the minimum quantity and `costmin` as the minimum cost; Kraken publishes no price
  bounds. Fees are the base tier of the pair's own schedule, in the quote asset — and
  `0` when the listing answers an empty schedule, which it has been observed doing.
- `tickers()` is one `Ticker` request for the whole catalogue, re-keyed by altname;
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

<!-- next -->

---

← [MEXC Market](mexc.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
