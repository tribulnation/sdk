# Market

> `Market` places orders and queries data for a single account/exchange/market. The
> surrounding objects (`Exchange`, `TradingVenue`, `TradingMarkets`) are thin scoping
> layers that resolve an ID down to a `Market` and forward the call.

Per-venue specifics live in [`impl/`](impl/): [dYdX](impl/dydx.md), [Hyperliquid](impl/hyperliquid.md), [MEXC](impl/mexc.md).

## Object hierarchy

Every call ultimately runs against a `Market`. The other classes just narrow an ID one
segment at a time and delegate:

```
TradingMarkets   (MarketSDK)        keyed by your account IDs
  └─ TradingVenue                   one account on one venue
       └─ Exchange / PerpExchange   one market type (spot/perp) on that venue
            └─ Market / PerpMarket   one instrument
```

- `TradingMarkets` — the top-level collection you construct (`MarketSDK`). Maps your
  configured account IDs to venues.
- `TradingVenue` — a single configured account on a single venue. Exposes `exchange()`,
  `perp_exchange()`, `exchanges()`.
- `Exchange` / `PerpExchange` — a market *type* on a venue (e.g. dYdX `perp`, MEXC `spot`).
  Exposes `market()`, `markets()`. `PerpExchange` additionally yields `PerpMarket`s.
- `Market` / `PerpMarket` — a single instrument. This is where the real work happens; all
  the query/trade methods are defined here, and everything above forwards to them.

`Exchange`, `TradingVenue`, and `TradingMarkets` each re-expose the full `Market` method
surface (`depth`, `place_order`, …) with a leading `market_id` argument, so you can make
one-shot scoped calls without holding a `Market`. They are pure convenience wrappers: each
resolves the market and calls the identical method on it.

`collateral()` / `perp_collateral()` are special: they support **both** exchange-level (no
market) and market-level calls via optional `market_id`. See
[Collateral & account risk](#collateral--account-risk).

## Market-ID grammar

IDs are colon-delimited and parsed left-to-right, one segment per scoping layer:

| Called on | ID shape |
| --- | --- |
| `TradingMarkets` (`MarketSDK`) | `<account_id>:<exchange_id>:<market_id>` |
| `TradingVenue` | `<exchange_id>:<market_id>` |
| `Exchange` / `PerpExchange` | `<market_id>` |

- **`account_id`** is the *key you registered in `accounts`* — not the venue's own name.
  Register `accounts.Dydx()` under `'dydx-1'` and the account ID is `dydx-1`. This lets you
  run several accounts on one venue side by side. The three built-in public accounts
  (`dydx`, `hyperliquid`, `mexc`) are always present unless you override those keys.
- **`exchange_id`** selects the market type on the venue: `perp` on dYdX, `spot` on MEXC,
  `spot` or a perp DEX name (empty string = the default perp DEX) on Hyperliquid.
- **`market_id`** is the venue-native instrument identifier and may itself contain colons
  (dYdX subaccount suffix, Hyperliquid spot index). Only the first two colons are
  significant to `TradingMarkets`; the rest is handed to the exchange verbatim
  (`id.split(':', 2)`).

Examples: `mexc_account1:spot:BTCUSDT`, `dydx:perp:BTC-USD`, `hyperliquid:spot:BTC/USDC:0`.

Equivalent ways to reach the same market:

```python
await sdk.depth('mexc_account1:spot:BTCUSDT')

venue = await sdk.venue('mexc_account1')
await venue.depth('spot:BTCUSDT')

exchange = await venue.exchange('spot')
await exchange.depth('BTCUSDT')

market = await exchange.market('BTCUSDT')
await market.depth()
```

Hold a `Market` reference in hot loops; use the scoped one-shot calls otherwise.

Note: a `Market` object's own `id` property is `f'{venue_id}:{exchange_id}:{market_id}'` and
uses the *venue's* canonical name (e.g. `dydx`), not the account key you looked it up by.

## Resolving IDs

- `TradingMarkets.venue(account_id)` → `TradingVenue`
- `TradingMarkets.exchange('<account_id>:<exchange_id>')` → `Exchange`
- `TradingMarkets.perp_exchange('<account_id>:<exchange_id>')` → `PerpExchange`
- `TradingMarkets.market('<account_id>:<exchange_id>:<market_id>')` → `Market`
- `TradingMarkets.perp_market(...)` / `TradingVenue.perp_market(...)` → `PerpMarket`
- `TradingMarkets.venues()` → the list of configured account IDs (built-ins included)
- `TradingVenue.exchanges()` → `[{'id': ..., 'type': 'spot' | 'perp'}, ...]`
- `Exchange.markets()` → list of available `market_id`s

Venues without perpetual support raise `NotImplementedError` from `perp_exchange()` (and
therefore from `perp_market`, `index`, `next_funding`, `funding_*`, `perp_position`).

## Method reference

All methods below are defined on `Market`; the perp-only block requires `PerpMarket`. The
same names exist on `Exchange`/`TradingVenue`/`TradingMarkets` with a leading `market_id`.

### Public market data

- `depth(*, levels=None) -> Book` — the order book. `levels` optionally caps the depth.
- `depth_stream(*, levels=None, queue_size=1, overflow='latest') -> AsyncContextManager[AsyncIterable[Book]]`
  — subscribe to live books. See [Streaming & overflow](#streaming--overflow).
- `rules(*, refetch=False) -> Rules` — tick/step sizes, fees, min/max, rounding helpers.
  Cached after the first call; pass `refetch=True` to bypass the cache.

### Your account data

- `query_order(id) -> OrderState | None` — state of one order. The base implementation
  scans `open_orders()`, so it only finds *open* orders unless a venue overrides it (dYdX
  does, and can return filled/canceled states too).
- `open_orders() -> Sequence[OrderState]` — your currently-open orders.
- `trades_history(start, end) -> PaginatedResponse[Trade]` — your fills over a window,
  paginated (async-iterate the pages).
- `trades_stream(*, queue_size=1000, overflow='fail') -> AsyncContextManager[AsyncIterable[Trade]]`
  — your live fills. See [Streaming & overflow](#streaming--overflow).
- `position() -> Position` — your open position size (base units). On a `PerpMarket` this
  returns the same data as `perp_position()`, just typed as the base `Position`.
- `collateral() -> Collateral` — the collateral bucket backing this market (see
  [Collateral & account risk](#collateral--account-risk)). On a `PerpMarket` this returns the
  same data as `perp_collateral()`, just typed as the base `Collateral`.
- `available_notional() -> Decimal` — the maximum notional you could open right now. For
  spot this is the free quote-token balance; for perps it is available collateral × the
  market's maximum leverage. This is *opening capacity*, a market-scoped projection of the
  bucket's `free_collateral` — it is deliberately **not** part of `collateral()`, which is
  about liquidation distance.

### Trading

- `place_order(order, *, settings={}) -> OrderResponse`
- `place_orders(orders, *, settings={}) -> Sequence[OrderResponse]` — concurrent `place_order`s.
- `cancel_order(id, *, settings={})`
- `cancel_orders(ids, *, settings={})` — concurrent `cancel_order`s.
- `cancel_open_orders(*, settings={})` — cancels everything `open_orders()` returns.

An `Order` is a `TypedDict`:

```python
{
  'qty': Num,    # signed base units: positive buys, negative sells
  'price': Num,  # always required by the SDK order shape
  'type': 'MARKET' | 'LIMIT' | 'POST_ONLY',
}
```

Order-type semantics (venue-agnostic contract):

- **`LIMIT`** — a normal limit order at `price`; may rest on the book unless `settings`
  request a different time-in-force.
- **`POST_ONLY`** — a maker-only limit at `price`; the venue rejects/cancels rather than
  taking liquidity.
- **`MARKET`** — immediate execution with price protection. `price` is the *worst
  acceptable* limit price (max to pay on a buy, min to accept on a sell). Venues with
  native market orders may ignore `price`; those without implement it as an aggressive
  non-resting (preferably IOC) limit order. **Market orders are only partially supported**
  and may partial-fill unless a stricter venue/setting semantics (e.g. FOK) applies.

`settings` is a per-venue dict keyed by venue name (`{'dydx': {...}}`,
`{'hyperliquid': {...}}`) — see each venue doc for accepted keys. If a venue can't honor
the requested semantics it should raise an API/validation error rather than silently place
a materially different order.

`OrderResponse` carries the order `id` (used for `cancel_order`/`query_order`) plus raw
`details`. `OrderState` carries `id`, `price`, signed `qty`, signed `filled_qty`, and an
`active` flag.

### Perpetual-only (`PerpMarket`)

- `index(*, settings={}) -> Decimal` — the index/oracle price.
- `next_funding() -> NextFunding` — upcoming funding `rate`, `time`, and `interval`;
  `.annualized` extrapolates the rate to a yearly figure.
- `funding_history(start, end) -> PaginatedResponse[FundingRate]` — historical funding rates.
- `funding_payments(start, end) -> PaginatedResponse[FundingPayment]` — funding you paid
  (positive) or received (negative), in quote units.
- `perp_position() -> PerpPosition` — position `size` plus average `entry_price`.
- `perp_collateral() -> PerpCollateral` — the perpetual collateral bucket backing this
  market, with maintenance-margin risk fields (see below). `collateral()` delegates to it.

## Collateral & account risk

`collateral()` answers a different question from `available_notional()`: not "how much can I
open?" but "how close am I to liquidation?". It is built on the **margin-bucket** model.

A **bucket** is a set of markets sharing one collateral pool and one liquidation event.
**An `Exchange` *is* one bucket**. Venues that don't support collateral raise
`NotImplementedError` at call time.

### Routing: exchange-level vs market-level

`collateral()` and `perp_collateral()` accept an optional `market_id` at every level. When
omitted they return the exchange's own bucket; when provided they delegate to the market's
mode-aware collateral:

| Called on | No arg / fewer segments | With market / more segments |
| --- | --- | --- |
| `Exchange.collateral()` | exchange bucket | `exchange.collateral('BTC-USD')` → market-level |
| `TradingVenue.collateral('perp')` | exchange bucket | `venue.collateral('perp:BTC-USD')` → market-level |
| `TradingMarkets.collateral('dydx:perp')` | exchange bucket | `sdk.collateral('dydx:perp:BTC-USD')` → market-level |

Same applies to `perp_collateral()` on `PerpExchange`/`TradingVenue`/`TradingMarkets`.

`Market.collateral()` is **mode-aware**: it returns the pool that actually backs *this*
market. For a cross-margin market that is the exchange bucket; for an isolated market it is
the market's own bucket. This is the accessor a liquidation watcher wants per watched market,
and it is the only model that expresses (e.g.) dYdX holding the same instrument both cross
(parent subaccount) and isolated (a child subaccount) at once.

Risk **never aggregates** across buckets: child/isolated buckets liquidate independently, so
a combined `maintenance_ratio` would be a lie. Additive history reads (trades, funding) may
default to an aggregate scope, but `collateral()` always scopes to exactly one bucket.

### Types

The returned types (`tribulnation.sdk.market`):

- **`Collateral`** — spot / base: `equity` (total account value in quote units) and
  `free_collateral` (not backing positions/orders — withdrawable opening capacity, **not**
  risk). No `None` fields ever: a field exists only if every supported venue can produce it
  truthfully.
- **`PerpCollateral`** (extends `Collateral`) — adds:
  - `initial_margin` — quote units; can't open new positions when `equity <= initial_margin`.
    Equals `equity - free_collateral`.
  - `maintenance_margin` — quote units; liquidation when `equity <= maintenance_margin`.
  - `leverage` — total position notional / equity, `0` when flat.
  - `margin_mode` — `'cross'` | `'isolated'`, always known.
  - `initial_ratio` property — `initial_margin / equity`. At `>= 1` you can't open more.
    This is what dYdX's UI shows as "margin usage".
  - `maintenance_ratio` property — `maintenance_margin / equity`. Liquidation at `>= 1`.
    `+Infinity` when `equity <= 0`.

  Per-position `liquidation_price` is deliberately excluded (dYdX can't give it cleanly).

Note: `initial_ratio` reaching 1.0 does **not** mean liquidation — it means you can't open
new positions. Between `initial_ratio = 1` and `maintenance_ratio = 1` there is a buffer
(typically ~2x, since MMF ≈ IMF/2). `maintenance_ratio` is the actual liquidation signal.

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
  `maintenance_ratio` properties. See [Collateral & account risk](#collateral--account-risk).
- **`Order`** / **`OrderResponse`** / **`OrderState`** — see [Trading](#trading).
- **`Trade`** — `id`, `price`, signed `qty`, `time`, `maker` flag, optional `fee`
  (`amount` + `asset`).
- **`FundingRate`** (`rate`, `time`), **`NextFunding`** (adds `interval`, `.annualized`),
  **`FundingPayment`** (`amount`, `time`). Rates are fractions of 1 (`0.01` = 1%).

## Streaming & overflow

`depth_stream()` and `trades_stream()` are async context managers yielding an async
iterable. A venue fans a single shared upstream out to every subscriber through a
*bounded per-subscriber queue*, controlled by two arguments:

- **`queue_size`** — how many items to buffer for *this* subscriber.
- **`overflow`** — what happens when that buffer is full:
  - `'latest'` — keep only the newest item; a slow consumer silently skips stale ones.
  - `'fail'` — fail the subscriber with a `NetworkError` so the caller can reconnect,
    rather than dropping data silently.

The defaults reflect each stream's intent:

| Stream | `queue_size` | `overflow` | Rationale |
| --- | --- | --- | --- |
| `depth_stream` | `1` | `'latest'` | You only care about the freshest book. |
| `trades_stream` | `1000` | `'fail'` | Don't drop your own fills silently. |

To capture *every* book (e.g. recording full depth history), pass `overflow='fail'` with a
larger `queue_size`.

The polling fallback used by generic markets has no shared upstream to fan out, so it
ignores `queue_size`/`overflow`; native venue subscriptions honor them.

## Usage example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()  # load credentials from .env

sdk = MarketSDK({
  'mexc_account1': accounts.Mexc(api_key='$MEXC_API_KEY', api_secret='$MEXC_API_SECRET'),
  # 'dydx', 'hyperliquid', and 'mexc' are available by default even without listing them
})

mexc = await sdk.market('mexc_account1:spot:BTCUSDT')
dydx = await sdk.market('dydx:perp:BTC-USD')

async with mexc.trades_stream() as my_trades:
  async for my_trade in my_trades:
    print(f'Hedging {my_trade}')
    await dydx.place_order({
      'type': 'LIMIT',
      'qty': -my_trade.qty,
      'price': my_trade.price,
    })
```

## Context, logging & retries

Every method above is wrapped with `@SDK.method`, so it participates in the active
`Context` (opt-in logging/retries). Because the scoping layers call through to the
`Market`, a persistent failure can be retried at each layer it passes through. See
[context.md](../context.md).
