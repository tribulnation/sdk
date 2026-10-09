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

# Types

Everything the Market surface returns is a dataclass or `TypedDict` under
`tribulnation.sdk.market`, the same on every venue. Prices, sizes and fees are `Decimal`,
timestamps are `datetime`, and quantities are signed base units: positive is a buy or a
long, negative a sell or a short. This page is the catalogue; [Methods](methods.md) says
which call returns what.

## Exchange history records

`ExchangeTrade` extends `Trade`, and `ExchangeFundingPayment` extends
`FundingPayment`. Each adds a required `market_id`: the native market ID within
the exchange, without account or exchange prefixes. Exchange-wide history calls
return these records; selected-market calls retain the existing base types.
See [exchange-wide account history](hierarchy.md#exchange-wide-account-history).

## Orders

An `Order` is what you pass to `place_order`:

```python
{
  'qty': Num,  # signed base units: positive buys, negative sells
  'price': Num,  # always required by the SDK order shape
  'type': 'MARKET' | 'LIMIT' | 'POST_ONLY',
  'client_order_id': str | None,  # optional: your own ID for the order
}
```

`Num` is anything numeric: `Decimal`, `int`, `float` or `str`, converted on the way in.

- `OrderResponse`: the order `id`, which `cancel_order` and `query_order` take, plus raw
  `details`.
- `OrderState`: `id`, `price`, signed `qty`, signed `filled_qty`, and an `active` flag.

Venue-specific options travel separately, in `settings`: a dict keyed by venue name
(`{'dydx': {...}}`, `{'hyperliquid': {...}}`), documented per venue under
[Implementations](implementations/index.md). Orders, `index`, `depth`, `depth_stream` and
`trades_stream` all take it, and each venue reads only its own key; a testnet reads its mainnet's key
(`'hyperliquid'` for `hyperliquid_testnet`). If a venue can't do what you asked for it
raises, rather than quietly placing a different order.

## Market data

- `Book`: `bids` and `asks` (`Book.Entry(price, qty)`, best-first), plus the arithmetic
  you'd otherwise write yourself: `best_bid`/`best_ask`, `mark_price`,
  `market_buy_price`/`market_sell_price` (by `qty=` or `notional=`),
  `buyable_at`/`sellable_at`, `with_fees`, `limit`, `merge`, `update` (apply an incremental
  diff), and in-place `buy`/`sell`. Quantities are base units, and
  `notional = price × qty`. `time` is the exchange time the book was current as of,
  timezone-aware UTC. For snapshot feeds (each message a complete book or its top
  levels) it is the time the snapshot was current: the venue's push, event or output
  time for it where the message carries one. For incremental (diff) and on-change
  feeds it is the time of the latest exchange event reflected (the matching-engine or
  transaction time where the venue offers several); it only advances when the book
  changes, so an old `time` on a quiet book means "unchanged", not necessarily stale.
  It is `None` when the venue provides no such timestamp, and is never local receive
  time or a transport header such as HTTP `Date`. Availability: Hyperliquid sets the
  block time on REST and WS; Aster the event/output time `E` (falling back to the
  transaction time `T`) on REST and WS; Lighter the WS `last_updated_at` (REST `depth`
  is `None`); dYdX never sets it. Derived books (`limit`, `with_fees`,
  `copy`) keep it, `merge` takes the oldest input's, and `update` takes the diff's.
  `update` replaces, adds and removes (zero quantity) levels, then uncrosses the book:
  some venues' diff streams can cross (dYdX's Indexer does by design, see
  [Uncrossing the orderbook](https://docs.dydx.xyz/interaction/data/watch-orderbook))
  and expect clients to drop the older level. While the best ask is at or below the best
  bid, a level the diff sets removes the existing level it crosses; if both come from
  the diff, the larger quantity wins (an equal one keeps the ask). Removals cross
  nothing, and crossings between existing levels are left as they are.
- `Rules`: `fee_asset`, `tick_size`, `step_size`, min and max qty and
  price (fixed and price-relative), optional standard `fees`, and an `api` flag for whether
  the instrument is tradable through the API at all. The helpers round, truncate and
  validate against those constraints (`round_price`, `trunc_qty`, `min_qty`, `notional2qty`,
  and so on): see [Your First Order](first-order.md). Fees are fractions of 1.
  Base/quote identities come from the Catalogue instrument, not `Rules`.
- `Ticker`: `last`, `bid`, `ask`, `bid_qty`, `ask_qty` and `base_volume_24h`, all optional.
- `Trade`: `id`, `price`, signed `qty`, `time`, a `maker` flag, and an optional `fee`
  (`amount` plus `asset`). `order_id` is the filled order's `OrderResponse.id`, and
  `client_order_id` the ID it was placed with; either is `None` where the venue
  doesn't report it. See [Client Order IDs](client-order-ids.md).

### Trading fees

`Fees` has four combined rates: `maker_buy`, `maker_sell`, `taker_buy`, and
`taker_sell`. Rates include applicable side, tax, special and market adjustments,
but exclude optional fee-payment discounts. Zero is genuinely free and negative
rates are rebates. `Rules.fees` describes the public standard non-VIP API schedule,
or is `None` when unknown. `await market.fees()` returns the configured account's
schedule; missing rates and request failures do not fall back to public fees.
Unsupported fee calculations raise `NotImplementedError`.

`book.with_fees(fees)` applies taker sell rates to bids and taker buy rates to asks;
use `maker=True` for maker rates. A single `Decimal` remains a shorthand for a
symmetric rate. This adjusts quoted notional costs, not actual settlement quantities,
fee-token conversion or rounding.

> [!NOTE]
> `Ticker` carries no 24h open, high, low or change on purpose. You can derive them from a
> sampled series, and storing them would freeze each venue's windowing choices into the
> type.

## Candles

- `Candle`: `time` (the open time, timezone-aware, never the close), `open`, `high`, `low`
  and `close`, plus optional `volume` (base units), `quote_volume` (quote turnover) and
  `trades`. Each optional field is `None` where the venue reports nothing for it: Coinbase,
  for one, publishes no quote volume.
- `CandleInterval`: `'1m' | '5m' | '15m' | '1h' | '4h' | '1d'`. Each implementation
  declares the subset it serves in `Market.CANDLE_INTERVALS`, so you can pick one without a
  failed request; any other interval raises `ValueError` before anything is sent. Venue
  extras (`1s`, `3d`, `1w`) are not exposed.

> [!NOTE]
> There is no `closed` flag: a candle is complete once `time + interval` is in the past.
> Only trade candles are served; mark- and index-price series are a different thing and
> would be a separate method, not a flag.

## Positions and collateral

- `Position`: `size`, in signed base units. `PerpPosition` adds `entry_price`.
- `Collateral`: `equity` and `free_collateral`. `PerpCollateral` adds `initial_margin`,
  `maintenance_margin`, `leverage`, `margin_mode`, and the `initial_ratio` and
  `maintenance_ratio` properties. See [Collateral & Risk](collateral.md) for what they mean
  and which pool they describe.

## Perpetuals

- `FundingRate`: `rate`, `time`, and an optional `premium`.
- `NextFunding`: the same plus `interval` and an `.annualized` property.
- `FundingPayment`: `amount` and `time`. The amount is a signed cash flow in quote
  units: positive when received, negative when paid. Funding rates retain their
  separate convention: a positive rate means longs pay shorts.
- `PerpStats`: `index`, always present, plus optional `mark`, `funding` (the predicted rate
  for the next settlement), `next_funding_time`, `funding_interval` and `open_interest`.

Rates are fractions of 1, so `0.01` is 1%. `premium` is the mark-vs-index quantity funding
is computed from, and it's `None` on venues that don't report it, like dYdX.

## Funding payment migration in SDK 2.10

Upgrade the SDK and your funding-capable adapters together: Hyperliquid 0.11.0,
dYdX 0.11.0, Bybit 0.5.0, Aster 0.5.0, and Lighter 0.4.0 (or newer). Older adapter
releases do not cap their SDK dependency and still return paid-positive amounts.

Refetch stored history or negate records from paid-positive versions exactly
once. Earlier Hyperliquid/dYdX data stored before the exchange-wide history sign
change already used received-positive amounts. Funding rates, trading fees and
Report observations are unchanged.

<!-- next -->

---

← [Client Order IDs](client-order-ids.md) · **Next:** [Methods](methods.md) →

<!-- /next -->
