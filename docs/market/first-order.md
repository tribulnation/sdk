<!-- github-only -->
<table><tr>
<td align="center"><a href="../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../earn/index.md">Earn</a></td>
<td align="center"><a href="../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../report/index.md">Report</a></td>
<td align="center"><a href="../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Your First Order

Placing an order takes four calls: read the market's rules, size the order against them,
place it, then check on it or cancel it. Let's walk through all four on a spot market.

The examples use `mexc_account1`, an account with trading credentials in your `sdk.toml`.
Every call also works scoped to a venue, exchange or market, as in
[Hierarchy & Scoping](hierarchy.md).

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK.load('sdk.toml')
```

## 1. Read the rules

Venues reject orders that don't fit their price and quantity grid, and every venue
publishes that grid differently. `rules()` normalizes it:

```python
rules = await sdk.rules('mexc_account1:spot:BTCUSDT')
```

```
Rules(
  fee_asset='USDT',
  tick_size=Decimal('0.10'), step_size=Decimal('0.00001'),
  fees=None,  # Unknown public schedule; query fees() for account rates.
)
```

Prices have to be a multiple of `tick_size`, quantities a multiple of `step_size`, and both
have minimums. You don't have to do that arithmetic yourself: `Rules` has helpers for it.

Base and quote identities come from the Catalogue instrument you selected, not
from `Rules`. `fee_asset` identifies the actual currency used for fees.

## 2. Size the order

```python
from decimal import Decimal

book = await sdk.depth('mexc_account1:spot:BTCUSDT')
price = rules.round_price(book.best_bid.price)
qty = rules.notional2qty(Decimal('250'), price=price)
```

`round_price` snaps the price to the tick grid. `notional2qty` turns a quote amount, 250
USDT here, into a base quantity on the step grid, and returns `None` when the result would
be below the market's minimum, so a too-small order fails in your code instead of at the
venue. `trunc_qty` and `round_qty` do the same when you already have a base quantity.

## 3. Place it

```python
response = await sdk.place_order('mexc_account1:spot:BTCUSDT', {
  'type': 'LIMIT', 'qty': qty, 'price': price,
})
```

```
OrderResponse(id='4834937', details={...})
```

`qty` is signed: positive buys, negative sells. There's no separate `side` field to get out
of step with it, and the same convention holds for `Position.size`, `OrderState.qty` and
`Trade.qty`. `price` is required even for `MARKET` orders, because a venue without real
market orders places a limit order there instead.

> [!NOTE]
> Anything a venue offers on top of the three order types, like a time-in-force, a
> reduce-only flag or a subaccount, goes in `settings`, keyed by venue:
> `settings={'dydx': {...}}`. If a venue can't do what you asked for it raises, rather than
> quietly placing a different order.

### Tag it with your own ID

Add a `client_order_id` to tag the order with an ID of your own.
`rules.random_client_id()` generates one in the format the market accepts:

```python
client_order_id = rules.random_client_id()
response = await sdk.place_order('mexc_account1:spot:BTCUSDT', {
  'type': 'LIMIT', 'qty': qty, 'price': price, 'client_order_id': client_order_id,
})
```

Its fills carry it back as `Trade.client_order_id`, next to `Trade.order_id`, which is
`response.id`. A strategy following its own fills can then tell its orders apart:

```python
async with sdk.trades_stream('mexc_account1:spot:BTCUSDT') as my_trades:
  async for trade in my_trades:
    if trade.client_order_id == client_order_id:
      print(trade.order_id, trade.qty, '@', trade.price)
```

The SDK sends the string unchanged, so an ID of your own must follow the venue's rules:
most limit its length and characters and reject an ID already in use. `random_client_id`
follows them by construction: 128 random bits as 32 hex digits, with `0x` in front on
Hyperliquid, as `rules.client_order_id_format` says (`'hex'` or `'0x-hex'`). Venues
without client order IDs ignore it, their `client_order_id_format` is `None`, and either
field is `None` on fills that don't report it:

| Venue | Sent as | `order_id` on fills | `client_order_id` on fills |
| --- | --- | --- | --- |
| Aster | `newClientOrderId`; perpetuals take up to 36 of `A-Z a-z 0-9 . : / _ -` | Stream | Stream |
| Binance | No trading | History and stream | Stream |
| Bit2Me | `clientOrderId` | History and stream | History and stream |
| Bitget | No trading | History and stream | UTA history and stream; Classic futures stream |
| Bybit | `orderLinkId`, up to 36 characters | History and stream | History and stream |
| Coinbase | `client_order_id` | History and stream | Stream |
| dYdX | Ignored | Stream | — |
| Hyperliquid | `cloid`: `0x` and 32 hex digits | History and stream | History and stream |
| Kraken | No trading | History and stream | Stream |
| Lighter | Ignored | History and stream | — |
| MEXC | `newClientOrderId` (spot) | History and stream | History and stream |

Where you give none, Aster, Binance and Bybit spot generate an ID, and so does the SDK on
Coinbase, which requires one: fills report that one. On Coinbase, reusing an ID doesn't
place a second order; you get back the order already placed under it. Deribit and KuCoin
serve public data only.

## 4. Check on it, or cancel it

`response.id` is what the rest of the surface takes:

```python
state = await sdk.query_order('mexc_account1:spot:BTCUSDT', response.id)
```

```
OrderState(id='4834937', price=Decimal('59500'), qty=Decimal('0.01'),
           filled_qty=Decimal('0'), active=True)
```

`query_order` returns `None` if the venue doesn't know the id anymore. `active` is the flag
to branch on, and `filled_qty` is signed like `qty`, so `qty - filled_qty` is what's still
resting. To list every open order instead of querying one, use `open_orders(market_id)`.

```python
await sdk.cancel_order('mexc_account1:spot:BTCUSDT', response.id)
```

Cancelling returns nothing. On most venues cancelling an order that already filled or
expired isn't an error either, so check the state if you need to know which happened.

## Next

Fills arrive on `trades_stream` instead of by polling `query_order`: see
[Streaming](streaming.md). If the market is a perpetual, `perp_collateral()` tells you how
much room the position has left, in [Collateral & Risk](collateral.md). Every signature is
in [Methods](methods.md), and every type they return in [Types](types.md).

<!-- next -->

---

← [Hierarchy & Scoping](hierarchy.md) · **Next:** [Collateral & Risk](collateral.md) →

<!-- /next -->
