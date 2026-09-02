# Methods

Every method below is defined on `Market`; the perpetual-only group needs a `PerpMarket`.
The same names exist on `Exchange`, `TradingVenue` and `TradingMarkets` with a leading
`market_id`, which is the form shown here. Examples assume:

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK.load('sdk.toml')
```

<!-- methods -->

## Orders

An `Order` is a `TypedDict`:

```python
{
  'qty': Num,  # signed base units: positive buys, negative sells
  'price': Num,  # always required by the SDK order shape
  'type': 'MARKET' | 'LIMIT' | 'POST_ONLY',
}
```

`settings` is a per-venue dict keyed by venue name (`{'dydx': {...}}`,
`{'hyperliquid': {...}}`) — see each venue doc for accepted keys. If a venue can't honor
the requested semantics it should raise an API/validation error rather than silently place
a materially different order.

`OrderResponse` carries the order `id` (used for `cancel_order`/`query_order`) plus raw
`details`. `OrderState` carries `id`, `price`, signed `qty`, signed `filled_qty`, and an
`active` flag.

## Data types

Returned types live under `tribulnation.sdk.market`:

- **`Book`** — `bids`/`asks` (`Book.Entry(price, qty)`, best-first). Rich helpers:
  `best_bid`/`best_ask`, `mark_price`, `market_buy_price`/`market_sell_price`
  (by `qty=` or `notional=`), `buyable_at`/`sellable_at`, `with_fees`, `limit`, `merge`,
  `update` (apply an incremental diff), and in-place `buy`/`sell`. All quantities are in
  base units; `notional = price × qty`.
- **`Rules`** — `base`/`quote`/`fee_asset`, `tick_size`, `step_size`, min/max qty and
  price (fixed and price-relative), `maker_fee`/`taker_fee`, and an `api` flag. Helpers
  round/truncate/validate against those constraints (`round_price`, `trunc_qty`,
  `min_qty`, `amount2qty`, …). Fees are fractions of 1.
- **`Position`** — `size` (signed base units). **`PerpPosition`** adds `entry_price`.
- **`Collateral`** — `equity`, `free_collateral`. **`PerpCollateral`** adds
  `initial_margin`, `maintenance_margin`, `leverage`, `margin_mode`, plus `initial_ratio` and
  `maintenance_ratio` properties. See [Collateral & account risk](collateral.md).
- **`Order`** / **`OrderResponse`** / **`OrderState`** — see [Orders](methods.md#orders).
- **`Trade`** — `id`, `price`, signed `qty`, `time`, `maker` flag, optional `fee`
  (`amount` + `asset`).
- **`FundingRate`** (`rate`, `time`, optional `premium`), **`NextFunding`** (adds
  `interval`, `.annualized`), **`FundingPayment`** (`amount`, `time`). Rates are fractions
  of 1 (`0.01` = 1%). `premium` is the mark-vs-index quantity funding is computed from, and
  is `None` on venues that don't report it (dYdX).
- **`Ticker`** — `last`, `bid`, `ask`, `bid_qty`, `ask_qty`, `base_volume_24h`, all
  optional. 24h open/high/low/change are deliberately absent: they are derivable from a
  sampled series, and storing them would freeze the venue's windowing choices.
- **`PerpStats`** — `index` (required) plus optional `mark`, `funding` (predicted rate for
  the next settlement), `next_funding_time`, `funding_interval`, `open_interest`.
