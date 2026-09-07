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

# Collateral & Risk

How close are you to liquidation? That's one call:

```python
c = await sdk.perp_collateral('dydx:perp:BTC-USD')
print(c.maintenance_ratio)
```

```
PerpCollateral(equity=Decimal('10240.55'), leverage=Decimal('2.10'), ...)
0.183  # liquidation at 1.0
```

`maintenance_ratio` is the number to watch, and it means the same thing on every venue that
implements the surface. For spot, `collateral()` returns the same object without the margin
fields. Venues that publish no collateral at all raise `NotImplementedError` when you call
it.

## The two ratios

`PerpCollateral` gives you two, and they answer different questions:

- `maintenance_ratio`: `maintenance_margin / equity`. You're liquidated at `1`, and it goes
  to `+Infinity` once equity reaches zero. This is the one to watch.
- `initial_ratio`: `initial_margin / equity`. At `1` you can't open anything new.

Hitting `initial_ratio = 1` isn't a liquidation. There's a buffer between the two, usually
about 2x, since the maintenance fraction is normally half the initial one. Only
`maintenance_ratio` crossing `1` ends the position.

For where those fractions come from, and how cross and isolated margining differ, see the
[Margining and Liquidations](https://tribulnation.com/blog/margining1) series on the blog.

## What the fields hold

`Collateral`, for spot and as the base of the perpetual type:

- `equity`: total account value, in quote units.
- `free_collateral`: the part not backing positions or orders. That's what you can withdraw
  or open with, not a risk measure. If the question is how big a position you can open, use
  `available_notional()` instead.

`PerpCollateral` adds:

- `initial_margin`: quote units. You can't open new positions once
  `equity <= initial_margin`. It equals `equity - free_collateral`.
- `maintenance_margin`: quote units. You're liquidated once `equity <= maintenance_margin`.
- `leverage`: total position notional over equity, `0` when you're flat.
- `margin_mode`: `'cross'` or `'isolated'`, always known.

No field is ever `None`. A field only exists if every supported venue can produce it
truthfully.

> [!NOTE]
> There's no per-position `liquidation_price`: not every venue can give one, and
> `maintenance_ratio` answers the same question.

## Which pool are you looking at?

Collateral only means something per **bucket**: a set of markets sharing one collateral pool
and one liquidation event. An `Exchange` is one bucket.

`collateral()` and `perp_collateral()` take an optional `market_id` at every level. Without
one you get the exchange's own bucket; with one you get that market's mode-aware collateral:

| Called on | No arg / fewer segments | With market / more segments |
| --- | --- | --- |
| `Exchange.collateral()` | exchange bucket | `exchange.collateral('BTC-USD')` → market-level |
| `TradingVenue.collateral('perp')` | exchange bucket | `venue.collateral('perp:BTC-USD')` → market-level |
| `TradingMarkets.collateral('dydx:perp')` | exchange bucket | `sdk.collateral('dydx:perp:BTC-USD')` → market-level |

`Market.collateral()` is mode-aware: it returns the pool that actually backs *this* market.
For a cross-margin market that's the exchange bucket; for an isolated one it's the market's
own. Some venues let you hold the same instrument both ways at once, which is why the
distinction matters.

> [!NOTE]
> Risk never aggregates across buckets. Child and isolated buckets liquidate independently,
> so a combined `maintenance_ratio` would be a lie. Additive history reads like trades and
> funding may default to an aggregate scope, but `collateral()` always scopes to exactly one
> bucket.

<!-- next -->

---

← [Your First Order](first-order.md) · **Next:** [Streaming](streaming.md) →

<!-- /next -->
