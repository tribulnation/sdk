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

## Orders

An `Order` is what you pass to `place_order`:

```python
{
  'qty': Num,  # signed base units: positive buys, negative sells
  'price': Num,  # always required by the SDK order shape
  'type': 'MARKET' | 'LIMIT' | 'POST_ONLY',
}
```

`Num` is anything numeric: `Decimal`, `int`, `float` or `str`, converted on the way in.

- `OrderResponse`: the order `id`, which `cancel_order` and `query_order` take, plus raw
  `details`.
- `OrderState`: `id`, `price`, signed `qty`, signed `filled_qty`, and an `active` flag.

Venue-specific options travel separately, in `settings`: a dict keyed by venue name
(`{'dydx': {...}}`, `{'hyperliquid': {...}}`), documented per venue under
[Implementations](implementations/index.md). If a venue can't do what you asked for it
raises, rather than quietly placing a different order.

## Market data

- `Book`: `bids` and `asks` (`Book.Entry(price, qty)`, best-first), plus the arithmetic
  you'd otherwise write yourself: `best_bid`/`best_ask`, `mark_price`,
  `market_buy_price`/`market_sell_price` (by `qty=` or `notional=`),
  `buyable_at`/`sellable_at`, `with_fees`, `limit`, `merge`, `update` (apply an incremental
  diff), and in-place `buy`/`sell`. Quantities are base units, and
  `notional = price × qty`.
- `Rules`: `fee_asset`, `tick_size`, `step_size`, min and max qty and
  price (fixed and price-relative), optional standard `fees`, and an `api` flag for whether
  the instrument is tradable through the API at all. The helpers round, truncate and
  validate against those constraints (`round_price`, `trunc_qty`, `min_qty`, `notional2qty`,
  and so on): see [Your First Order](first-order.md). Fees are fractions of 1.
  Base/quote identities come from the Catalogue instrument, not `Rules`.
- `Ticker`: `last`, `bid`, `ask`, `bid_qty`, `ask_qty` and `base_volume_24h`, all optional.
- `Trade`: `id`, `price`, signed `qty`, `time`, a `maker` flag, and an optional `fee`
  (`amount` plus `asset`).

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
- `FundingPayment`: `amount` and `time`.
- `PerpStats`: `index`, always present, plus optional `mark`, `funding` (the predicted rate
  for the next settlement), `next_funding_time`, `funding_interval` and `open_interest`.

Rates are fractions of 1, so `0.01` is 1%. `premium` is the mark-vs-index quantity funding
is computed from, and it's `None` on venues that don't report it, like dYdX.

<!-- next -->

---

← [Streaming](streaming.md) · **Next:** [Methods](methods.md) →

<!-- /next -->
