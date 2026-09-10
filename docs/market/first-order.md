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
