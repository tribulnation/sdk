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
implements the surface. Venues that publish no collateral at all raise `NotImplementedError`
when you call it.

Spot markets have no margin and no liquidation: they have [balances](#spot-balances). And
every market names the money its orders spend with a [collateral ID](#collateral-ids), so
strategies on one account never reserve the same balance twice.

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

`Collateral` is the money behind a collateral ID, and the base of the perpetual type:

- `equity`: total value, in the collateral's own units: the asset itself for a spot ID, the
  pool's settlement asset for a margin pool.
- `free_collateral`: the part not held by open orders or margin. That's what new orders can
  use, not a risk measure.

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

## Spot balances

A spot pair spends its quote asset on a buy and its base asset on a sell, so it reports both:

```python
b = await sdk.balances('hyperliquid:spot:UBTC/USDC:142')
rules = await sdk.spot_rules('hyperliquid:spot:UBTC/USDC:142')
```

```
SpotBalances(base=Balance(total=Decimal('0.5'), free=Decimal('0.4')),
             quote=Balance(total=Decimal('9875.20'), free=Decimal('7640.00')))
SpotRules(base='197', quote='0', ...)  # Hyperliquid names tokens by index
```

`free` excludes what open orders hold: `base.free` is the most a sell can spend, `quote.free`
the most a buy can. Spot rules name the pair's assets in the venue's own asset IDs (the form
each [implementation page](implementations/index.md) states); perpetual rules don't, since
a contract's denomination need not be its collateral.

## How big can you open?

Collateral tells you how far you are from liquidation. To size a new perpetual position, ask
for opening capacity instead:

```python
notional = await sdk.available_notional('dydx:perp:ETC-USD')
leverage = await sdk.leverage('dydx:perp:ETC-USD')
price = (await sdk.depth('dydx:perp:ETC-USD')).best_ask.price
qty = notional / price  # the largest buy the account can open right now
```

```
Decimal('1200.00')  # free collateral 120 x leverage 10
Decimal('10')
```

- `leverage()` is the multiple of free collateral this account can open as notional on this
  market: opening `n` of notional takes `n / leverage` of collateral. It is account-specific,
  e.g. Hyperliquid's per-asset leverage setting, which is why it lives on the market and not
  in the public `rules()`, nor in `collateral()` (a bucket shared by many markets has no
  single leverage). It's cached after the first call; pass `refetch=True` after changing the
  setting elsewhere.
- `available_notional()` is `free_collateral × leverage()`, using the collateral backing that
  market. A venue may override it with a more precise figure, e.g. when an isolated position
  is funded from the cross pool rather than its own bucket; each
  [implementation page](implementations/index.md) says what it uses.

Both exist on margin (perpetual) markets only. On spot, size from `balances()`: a buy up to
`quote.free / price`, a sell up to `base.free`.

Venues without account leverage raise `NotImplementedError` from `leverage()` and keep
their own venue-specific `available_notional()`. Neither figure subtracts fees, nor checks a venue's
notional caps or margin tiers beyond what its leverage already reflects.

## Collateral IDs

A collateral ID names the money that funds new orders on a market. Markets sharing money
return the same ID, so keeping one reservation ledger per ID never counts a balance twice:

| Order | Reserves on | Capacity |
| --- | --- | --- |
| Spot buy | `collateral_ids(market).quote` | `quote.free` |
| Spot sell | `collateral_ids(market).base` | `base.free`, no shorting |
| Perpetual | `collateral_id(market)` | `free_collateral × leverage()` |

IDs are opaque strings led by the account key, like market IDs:

- A spot asset is `<account>:<spot exchange>:<asset>`: `margin-trade:spot:USDC`, or
  `hyperliquid:spot:0` where the venue's asset IDs are indices.
- A margin pool is `<account>:<perp exchange>`: `dydx:perp`, `aster:perp`.
- On a **unified** account, perpetual margin *is* a spot balance, so a perpetual returns that
  asset's spot ID. Every Hyperliquid perpetual returns its dex collateral token's spot ID
  (`hyperliquid:spot:0` for USDC), the same ID USDC-quoted spot pairs return.
- An **isolated** position still returns the pool its new margin is drawn from; its own
  bucket only matters for liquidation, through `perp_collateral()`.
- Venues with separate spot and perpetual wallets (Margin Trade, Aster) return distinct IDs:
  `margin-trade:spot:USDC` and `margin-trade:perp`.

`sdk.collateral(id)` resolves any of them:

```python
id = await sdk.collateral_id('hyperliquid::ETH')
c = await sdk.collateral(id)
```

```
'hyperliquid:spot:0'
Collateral(equity=Decimal('9875.20'), free_collateral=Decimal('7640.00'))
```

A spot ID resolves to the asset's balance (`equity = total`, `free_collateral = free`), a
pool ID to the exchange's `PerpCollateral`. `free_collateral` already excludes resting
orders, so a reservation ledger only subtracts what it has sent but the venue hasn't
counted yet.

## Which bucket backs a perpetual?

Liquidation is per **bucket**: a set of markets sharing one collateral pool and one
liquidation event. A perpetual exchange is one bucket, and `perp_collateral()` reads one at
every level:

| Called on | No arg / fewer segments | With market / more segments |
| --- | --- | --- |
| `PerpExchange.perp_collateral()` | exchange bucket | `exchange.perp_collateral('BTC-USD')` → market-level |
| `TradingVenue.perp_collateral('perp')` | exchange bucket | `venue.perp_collateral('perp:BTC-USD')` → market-level |
| `TradingMarkets.perp_collateral('dydx:perp')` | exchange bucket | `sdk.perp_collateral('dydx:perp:BTC-USD')` → market-level |

A market's `collateral()` is mode-aware: it returns the pool that actually backs *this*
market. For a cross-margin market that's the exchange bucket; for an isolated one it's the
market's own. Some venues let you hold the same instrument both ways at once, which is why
the distinction matters.

> [!NOTE]
> Risk never aggregates across buckets. Child and isolated buckets liquidate independently,
> so a combined `maintenance_ratio` would be a lie. Additive history reads like trades and
> funding may default to an aggregate scope, but `collateral()` always scopes to exactly one
> bucket.

## Migrating from 2.x

SDK 3.0 removes the spot stand-ins without a deprecation release
([ADR 0051](https://github.com/tribulnation/sdk/blob/main/dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)):

| 2.x | 3.0 |
| --- | --- |
| `market.position()` on spot (total base, order holds included) | `market.balances().base` (`total`, and `free` without holds) |
| `market.collateral()` on spot (the quote balance) | `market.balances().quote` |
| `market.available_notional()` on spot (buys only) | `balances()`: `quote.free` for buys, `base.free` for sells |
| `sdk.collateral('<account>:<exchange>:<market>')` | `sdk.perp_collateral(<market id>)`; `sdk.collateral()` now takes collateral IDs |
| `sdk.collateral('<account>:spot')` (raised) | `sdk.collateral('<account>:spot:<asset>')` |
| `isinstance(market, PerpMarket)` | `is_perp(market)`, `is_spot(market)`, or `market.kind` |

`Market` keeps books, trades, orders, rules and fees. `SpotMarket` and `MarginMarket`
(`PerpMarket` derives from it) hold the account reads above; `SpotExchange` and
`PerpExchange` split the same way, and only `PerpExchange` has an exchange-wide
`collateral()`. The gateway protocol is `tribulnation-gateway.v2`: upgrade the gateway and
its clients together.

<!-- next -->

---

← [Your First Order](first-order.md) · **Next:** [Streaming](streaming.md) →

<!-- /next -->
