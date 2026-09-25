# %% [markdown]
# # lighter `market` PoC (perp)
#
# Maps `typed_lighter` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Runs against Lighter's **testnet** (`LIGHTER_TESTNET_*` credentials): perps ETH, BTC and SOL. IDs are the venue's numeric ids as decimal strings: market ids are `market_id` (`'4095'` is testnet ETH, `'0'` mainnet ETH), asset ids are `asset_id` (`'3'` is USDC on both). Only mainnet instruments are catalogued.
#
# A second testnet account, a sub-account of the first (`LIGHTER_TESTNET_SUB_*`), is the counterparty for maker fills and holds the isolated-margin position.

# %%
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Literal,
  Mapping,
  Sequence,
)
import asyncio
import os
import time

from dotenv import load_dotenv
from typed_lighter import Lighter
from typed_lighter.api.account.get import DetailedAccount
from typed_lighter.api.markets.order_book_details import PerpsOrderBookDetail
from typed_lighter.schemas import (
  AccountPosition,
  Candle as LighterCandle,
  MarketStats,
  Order as LighterOrder,
  PriceLevel,
  SimpleOrder,
  Trade as LighterTrade,
)

from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  ExchangeFundingPayment,
  ExchangeTrade,
  Fees,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  PerpStats,
  Position,
  Rules,
  Settings,
  Ticker,
  Trade,
)
from tribulnation.sdk.market.exchange import OverflowPolicy
from tribulnation.sdk.market.types.candles import EPOCH, candle_width, candle_windows

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(Lighter.new(network='testnet'))
ACCOUNT = client.signer.account_index
counterparty = await stack.enter_async_context(
  Lighter.new(
    network='testnet',
    account_index=int(os.environ['LIGHTER_TESTNET_SUB_ACCOUNT_INDEX']),
    api_key_index=int(os.environ['LIGHTER_TESTNET_SUB_API_KEY_INDEX']),
    api_private_key=os.environ['LIGHTER_TESTNET_SUB_API_PRIVATE_KEY'],
  )
)
SUB = counterparty.signer.account_index

MARKETS = ['4095', '4096', '4097']
ETH = '4095'
USDC = '3'
"""Perps margin, PnL, fees and funding all settle in USDC, asset id `3`."""
FUNDING_INTERVAL = timedelta(hours=1)
"""Lighter settles funding every hour, on the hour."""
FEE_TICK = Decimal('1e-6')
"""Fee ticks are parts per million: tier `plus` reports 50/50 (0.5 bps), `premium` 40/280 (0.0040%/0.0280%), matching the docs' tier table and the balance changes measured below."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


async def perp_details() -> dict[str, PerpsOrderBookDetail]:
  """Every perp market's details, keyed by market id (the other type's list is `null`)."""
  details = await client.api.markets.order_book_details(filter='perp')
  return {str(d['market_id']): d for d in details['order_book_details'] or []}


async def all_stats() -> dict[str, MarketStats]:
  """The `market_stats:all` snapshot, keyed by market id: the one venue source of the predicted funding rate."""
  async with client.streams.market_stats('all') as stream:
    async for frame in stream:
      stats = frame['market_stats']
      rows = stats.values() if isinstance(stats, dict) else [stats]
      return {str(s['market_id']): s for s in rows}  # type: ignore[union-attr]
  raise RuntimeError('market_stats stream closed before its snapshot')


details = await perp_details()
version('typed-lighter'), ACCOUNT, SUB, {m: d['symbol'] for m, d in details.items()}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_lighter',
    'Lighter',
    grep=r'^api\.markets\.|^api\.account\.(get|limits|position_funding|orders\.)|^streams\.(order_book|market_stats|account_market|user_stats)|^tx\.(create_order|cancel_order|cancel_all_orders|update_leverage|update_margin)',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """Every perp market id, inactive ones included (`rules().api` says whether it trades)."""
  return list(await perp_details())


listed = await markets()
assert set(MARKETS) <= set(listed)
{m: (details[m]['symbol'], details[m]['status']) for m in listed}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.
#
# `orderBookOrders` returns individual resting orders, `limit` per side (at most 250), best first. They are summed per price into levels; when a side comes back full, its last level may be missing orders beyond the limit, so it is dropped rather than reported short.

# %%
BOOK_ORDERS_LIMIT = 250


def aggregate(orders: Sequence[SimpleOrder], *, full: bool) -> list[Book.Entry]:
  """Sum orders into price levels, keeping the venue's best-first order."""
  levels: dict[Decimal, Decimal] = {}
  for o in orders:
    levels[o['price']] = levels.get(o['price'], Decimal(0)) + o['remaining_base_amount']
  entries = [Book.Entry(price, qty) for price, qty in levels.items()]
  return entries[:-1] if full else entries


async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Aggregate the top resting orders of each side into levels."""
  raw = await client.api.markets.order_book_orders(
    market_id=int(market_id), limit=BOOK_ORDERS_LIMIT
  )
  book = Book(
    bids=aggregate(raw['bids'], full=raw['total_bids'] == BOOK_ORDERS_LIMIT),
    asks=aggregate(raw['asks'], full=raw['total_asks'] == BOOK_ORDERS_LIMIT),
  )
  return book.limit(levels) if levels is not None else book


books = {m: await depth(m) for m in MARKETS}
{m: (len(b.bids), len(b.asks), b.best_bid, b.best_ask) for m, b in books.items()}


# %%
# The REST limit ceiling, and REST levels against the WS snapshot (testnet and mainnet ETH).
async def ws_levels(c: Lighter, market_id: int) -> tuple[int, int]:
  """Level counts of an `order_book` snapshot."""
  async with c.streams.order_book(market_id) as stream:
    async for frame in stream:
      return len(frame['order_book']['bids']), len(frame['order_book']['asks'])
  raise RuntimeError('order_book stream closed before its snapshot')


probe: dict[str, Any] = {}
for limit in (250, 251):
  try:
    r = await client.api.markets.order_book_orders(market_id=int(ETH), limit=limit)
    probe[f'limit {limit}'] = (r['total_bids'], r['total_asks'])
  except Exception as e:
    probe[f'limit {limit}'] = f'{type(e).__name__}: {e}'
testnet_rest = await depth(ETH)
probe['testnet rest levels'] = (len(testnet_rest.bids), len(testnet_rest.asks))
probe['testnet ws levels'] = await ws_levels(client, int(ETH))
async with Lighter.new(public=True) as mainnet:
  raw = await mainnet.api.markets.order_book_orders(
    market_id=0, limit=BOOK_ORDERS_LIMIT
  )
  probe['mainnet rest levels'] = (
    len(aggregate(raw['bids'], full=True)),
    len(aggregate(raw['asks'], full=True)),
  )
  probe['mainnet ws levels'] = await ws_levels(mainnet, 0)
probe


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.
#
# `order_book/{id}` sends the full book on subscribe, then changed levels every 50 ms (size `0` deletes a level). Each frame's `begin_nonce` must equal the previous frame's `nonce`; a gap means a missed update and fails the stream.


# %%
def levels_of(rows: Sequence[PriceLevel]) -> list[Book.Entry]:
  """Book entries from venue price levels."""
  return [Book.Entry(r['price'], r['size']) for r in rows]


@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Maintain a local book from the snapshot and its incremental updates."""
  async with client.streams.order_book(int(market_id)) as stream:

    async def books():
      book = Book()
      nonce: int | None = None
      async for frame in stream:
        state = frame['order_book']
        if frame['type'] == 'subscribed/order_book':
          book = Book(bids=levels_of(state['bids']), asks=levels_of(state['asks']))
        else:
          if nonce is not None and state['begin_nonce'] != nonce:
            raise RuntimeError(f'order_book gap: {nonce} -> {state["begin_nonce"]}')
          book.update(
            Book(bids=levels_of(state['bids']), asks=levels_of(state['asks']))
          )
        nonce = state['nonce']
        yield book.limit(levels) if levels is not None else book.copy()

    yield books()


seen: list[tuple[int, int, Decimal, Decimal]] = []
async with depth_stream(ETH, levels=10) as stream:
  async for update in stream:
    seen.append(
      (len(update.bids), len(update.asks), update.best_bid.price, update.best_ask.price)
    )
    if len(seen) == 5:
      break
seen


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.
#
# One `market_stats:all` snapshot carries last price, best bid/ask and 24h volumes for every perp. It has no size at the best levels, so `bid_qty`/`ask_qty` stay `None`.


# %%
def price_or_none(value: Decimal | Literal['']) -> Decimal | None:
  """A `market_stats` price, or `None` where the venue sends `""` (missing)."""
  return None if value == '' else value


async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Tickers from the `market_stats:all` snapshot."""
  stats = await all_stats()
  wanted = stats.keys() if markets is None else [m for m in markets if m in stats]
  return {
    m: Ticker(
      last=stats[m]['last_trade_price'],
      bid=price_or_none(stats[m]['best_bid_price']),
      ask=price_or_none(stats[m]['best_ask_price']),
      base_volume_24h=Decimal(str(stats[m]['daily_base_token_volume'])),
      quote_volume_24h=Decimal(str(stats[m]['daily_quote_token_volume'])),
    )
    for m in wanted
  }


{
  'all': len(await tickers()),
  'selected': await tickers(MARKETS),
  'empty': await tickers([]),
}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.
#
# Tick and step are the signing scales (`10^-supported_*_decimals`). `maker_fee`/`taker_fee` are the standard-account rates, in percent (`0.0000` on every market of both deployments: the docs' standard tier trades fee-free). The notional cap `order_quote_limit` has no `Rules` field and stays in `details`.


# %%
def percent(value: Decimal) -> Decimal:
  """A venue percentage as a fraction."""
  return value / 100


def standard_fees(d: PerpsOrderBookDetail) -> Fees:
  """The market's standard-account rates; a disabled fee is zero."""
  maker = percent(d['maker_fee']) if d['is_maker_fee_enabled'] else Decimal(0)
  taker = percent(d['taker_fee']) if d['is_taker_fee_enabled'] else Decimal(0)
  return Fees.symmetric(maker=maker, taker=taker)


async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Precision, size and notional floors and standard fees from `orderBookDetails`."""
  d = (await perp_details())[market_id]
  return Rules(
    fee_asset=USDC,
    tick_size=Decimal(1).scaleb(-d['supported_price_decimals']),
    step_size=Decimal(1).scaleb(-d['supported_size_decimals']),
    fixed_min_qty=d['min_base_amount'],
    min_value=d['min_quote_amount'],
    fees=standard_fees(d),
    api=d['status'] == 'active',
    details={
      'symbol': d['symbol'],
      'order_quote_limit': d['order_quote_limit'],
      'multiplier': d['multiplier'],
      'market_config': d['market_config'],
    },
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.
#
# `account/limits` reports the account's current maker and taker fee ticks, in parts per million, for every market (spot fills carry the same ticks). The same rate applies to buys and sells.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """The account's current maker/taker ticks."""
  limits = await client.api.account.limits(ACCOUNT)
  return Fees.symmetric(
    maker=limits['current_maker_fee_tick'] * FEE_TICK,
    taker=limits['current_taker_fee_tick'] * FEE_TICK,
  )


limits = await client.api.account.limits(ACCOUNT)
{
  'tier': (
    limits['user_tier'],
    limits['current_maker_fee_tick'],
    limits['current_taker_fee_tick'],
  ),
  'fees': await fees(ETH),
}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.
#
# The venue's CDN caches `candles` without `start_timestamp` in the key (typed-lighter 0.2.0 dropped `candles_paged` for it), so the walk requests grid-aligned windows of at most 500 opens, each sending its own number of opens as `count_back`: with the window's end, that identifies the request. Where the venue has fewer rows it extends the range backwards; rows outside the window are dropped. Zero fields are omitted by the venue, so a missing volume is zero; `i` is the last trade id, not a count.

# %%
RESOLUTIONS: dict[CandleInterval, Literal['1m', '5m', '15m', '1h', '4h', '1d']] = {
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '1h',
  '4h': '4h',
  '1d': '1d',
}


def parse_candle(c: LighterCandle) -> Candle:
  """An SDK candle from a venue candle; the venue omits zero fields."""
  return Candle(
    time=c['t'],
    open=Decimal(str(c.get('o', 0))),
    high=Decimal(str(c.get('h', 0))),
    low=Decimal(str(c.get('l', 0))),
    close=Decimal(str(c.get('c', 0))),
    volume=Decimal(str(c.get('v', 0))),
    quote_volume=Decimal(str(c.get('V', 0))),
  )


async def candles(
  market_id: str,
  /,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
  *,
  on: Lighter | None = None,
):
  """Candles opening in `[start, end)`, one window per request (`on` another client)."""
  venue = on or client
  width = candle_width(interval)
  for lower, upper in candle_windows(start, end, interval, size=500):
    offset = (lower - EPOCH) % width
    lower = lower if not offset else lower - offset + width
    count = -((lower - upper) // width)
    if count <= 0:
      continue
    response = await venue.api.markets.candles(
      market_id=int(market_id),
      resolution=RESOLUTIONS[interval],
      start_timestamp=lower,
      end_timestamp=upper,
      count_back=count,
    )
    yield [
      parse_candle(c)
      for c in response['c']
      if lower <= c['t'] < upper and start <= c['t'] < end
    ]


candle_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
candle_probe = {}
for interval in RESOLUTIONS:
  width = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}[interval]
  window_start = candle_end - timedelta(minutes=width * 5)
  rows = [
    c async for page in candles(ETH, interval, window_start, candle_end) for c in page
  ]
  candle_probe[interval] = (len(rows), rows[0] if rows else None)
candle_probe

# %%
# Cross-page: 1200 one-minute candles, with no duplicates or gaps (testnet serves them in one page).
cross_start = candle_end - timedelta(minutes=1200)
pages = [page async for page in candles(ETH, '1m', cross_start, candle_end)]
times = sorted(c.time for page in pages for c in page)
{
  'pages': [len(p) for p in pages],
  'unique': len(set(times)) == len(times),
  'first': times[0],
  'last': times[-1],
  'missing_minutes': 1200 - len(times),
}

# %%
# CDN check (mainnet, public): a 550-hour walk right after a 72-hour one with the same end
# still gets every candle, and a start between grid points no longer fails.
async with Lighter.new(public=True) as mainnet:
  grid_end = datetime.now(timezone.utc).replace(
    minute=0, second=0, microsecond=0
  ) - timedelta(days=1)
  short = [
    c
    async for p in candles(
      '1', '1h', grid_end - timedelta(hours=72), grid_end, on=mainnet
    )
    for c in p
  ]
  long = [
    c
    async for p in candles(
      '1', '1h', grid_end - timedelta(hours=550), grid_end, on=mainnet
    )
    for c in p
  ]
  unaligned = [
    c
    async for p in candles(
      '0', '5m', grid_end - timedelta(minutes=5 * 1000 + 3), grid_end, on=mainnet
    )
    for c in p
  ]
{'72h': len(short), '550h': len(long), 'unaligned 5m x1000': len(unaligned)}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.
#
# The SDK order id is the `client_order_index` the SDK assigns at placement: `place_order` only learns a transaction hash (the venue assigns `order_index` on execution), and `cancel_order` accepts the client index in place of `order_index`. `accountOrders` looks client indexes up directly, over the last 10K active orders and the last 1K inactive orders of the past 24 hours. Exercised on live orders in the trading round trip below.

# %%
ACTIVE_STATUSES = {'in-progress', 'pending', 'open'}


def parse_order(o: LighterOrder) -> OrderState:
  """An SDK order state from a venue order; sells are negative."""
  sign = -1 if o['is_ask'] else 1
  return OrderState(
    id=o['client_order_id'],
    price=o['price'],
    qty=o['initial_base_amount'] * sign,
    filled_qty=o['filled_base_amount'] * sign,
    active=o['status'] in ACTIVE_STATUSES,
    details=o,
  )


async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Look the order up by its client index."""
  orders = await client.api.account.orders.by_client_index(
    [int(id)], account_index=ACCOUNT
  )
  for o in orders['orders']:
    if o['market_index'] == int(market_id):
      return parse_order(o)


{'missing': await query_order(ETH, '123456789')}


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders. Exercised on live orders in the trading round trip below.


# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """The market's active orders."""
  orders = await client.api.account.orders.active(
    account_index=ACCOUNT, market_id=int(market_id)
  )
  return [parse_order(o) for o in orders['orders']]


{m: await open_orders(m) for m in MARKETS}


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one market or the whole exchange.
#
# `trades` sorted by timestamp, newest first, filtered to the account and to perps; the exchange-wide form omits `market_id`, so delisted markets are included. The account's side is whichever of `bid_account_id`/`ask_account_id` it is; it was maker when its side is the resting one (`is_maker_ask`). The fee is the trade's tick for the account's role (`maker_fee`/`taker_fee`, absent when zero) times the USDC notional `usd_amount`; the fee checks below match the balance changes to 1e-9.

# %%
TRADES_PAGE = 100


def role(t: LighterTrade, account: int) -> tuple[bool, bool]:
  """Whether `account` sold in the trade, and whether it was the maker."""
  is_ask = t['ask_account_id'] == account
  return is_ask, t['is_maker_ask'] == is_ask


def parse_trade(t: LighterTrade, account: int = ACCOUNT) -> Trade:
  """The account's fill from a venue trade, with its USDC fee."""
  is_ask, maker = role(t, account)
  tick = t.get('maker_fee', 0) if maker else t.get('taker_fee', 0)
  return Trade(
    id=t['trade_id_str'],
    price=t['price'],
    qty=-t['size'] if is_ask else t['size'],
    time=t['timestamp'],
    maker=maker,
    fee=Trade.Fee(amount=t['usd_amount'] * tick * FEE_TICK, asset=USDC),
    details=t,
  )


async def trades_history(
  market_id: str | None, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Personal perp fills with `start <= time <= end`, newest first."""
  pages = client.api.account.orders.trades_paged(
    'timestamp',
    limit=TRADES_PAGE,
    account_index=ACCOUNT,
    market_type='perp',
    market_id=None if market_id is None else int(market_id),
  )
  async for page in pages:
    rows: list[Trade] = []
    for t in page:
      if t['timestamp'] > end:
        continue
      if t['timestamp'] < start:
        if rows:
          yield rows
        return
      trade = parse_trade(t)
      rows.append(
        trade
        if market_id is not None
        else ExchangeTrade(**vars(trade), market_id=str(t['market_id']))
      )
    if rows:
      yield rows


history_start = end - timedelta(days=30)
by_market = {
  m: [t async for page in trades_history(m, history_start, end) for t in page]
  for m in MARKETS
}
exchange_wide = [
  t async for page in trades_history(None, history_start, end) for t in page
]
{
  'per_market': {
    m: [(t.price, t.qty, t.maker, t.fee) for t in ts[:4]] for m, ts in by_market.items()
  },
  'exchange': (len(exchange_wide), exchange_wide[0] if exchange_wide else None),
  'exchange_equals_union': sorted(t.id or '' for t in exchange_wide)
  == sorted(t.id or '' for ts in by_market.values() for t in ts),
}


# %%
# Helpers for the live fills below.
async def usdc_margin(c: Lighter) -> Decimal:
  """The account's perps USDC balance."""
  acct = (await c.api.account.get({'by': 'index', 'value': c.signer.account_index}))[
    'accounts'
  ][0]
  return next(a['margin_balance'] for a in acct['assets'] if a['asset_id'] == int(USDC))


async def post_only(c: Lighter, market_id: str, qty: Decimal, price: Decimal) -> int:
  """Rest a post-only order for `c`; returns its client index."""
  scaler = await c.scaler(int(market_id))
  index = next_client_index()
  await c.tx.create_order(
    {
      'order_type': 'limit',
      'market_index': int(market_id),
      'client_order_index': index,
      'base_amount': scaler.size(abs(qty)),
      'is_ask': qty < 0,
      'price': scaler.price(price),
      'time_in_force': 'post-only',
    }
  )
  return index


def next_client_index() -> int:
  """A fresh client order index: microseconds since the epoch, modulo 2^48."""
  return time.time_ns() // 1000 % 2**48


async def crossing_price(market_id: str, *, sell: bool) -> Decimal:
  """A price inside the spread (or just at the touch), so the counterparty's post-only order is best."""
  book = await depth(market_id, levels=1)
  tick = (await rules(market_id)).tick_size
  if sell:
    return max(book.best_ask.price - tick, book.best_bid.price + tick)
  return min(book.best_bid.price + tick, book.best_ask.price - tick)


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.
#
# `account_market/{market}/{account}` pushes the account's new trades on that market. The subscribe snapshot is skipped: it replays existing state.


# %%
@asynccontextmanager
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """The account's new fills on one market."""
  async with client.streams.account_market(
    market_id=int(market_id), account_index=ACCOUNT
  ) as stream:

    async def trades():
      async for frame in stream:
        if frame['type'] == 'subscribed/account_market':
          continue
        for t in frame['trades']:
          yield parse_trade(t)

    yield trades()


async def fill_while_streaming(market_id: str, qty: Decimal):
  """Take `qty` at market while subscribed, and return the first streamed fill."""
  async with trades_stream(market_id) as stream:
    first = asyncio.ensure_future(anext(aiter(stream)))
    await asyncio.sleep(1)
    book = await depth(market_id, levels=1)
    worst = (book.best_ask.price if qty > 0 else book.best_bid.price) * (
      Decimal('1.02') if qty > 0 else Decimal('0.98')
    )
    tick = (await rules(market_id)).tick_size
    placed = await place_order(
      market_id, {'type': 'MARKET', 'qty': qty, 'price': worst.quantize(tick)}
    )  # noqa: F821 -- defined in `place_order` below
    return placed.id, await asyncio.wait_for(first, 15)


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def account(c: Lighter = client) -> DetailedAccount:
  """The account's details."""
  accounts = await c.api.account.get({'by': 'index', 'value': c.signer.account_index})
  return accounts['accounts'][0]


async def position(market_id: str, /) -> Position:
  """Defers to `perp_position`."""
  return await perp_position(market_id)


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.
#
# Free cross collateral (see `perp_collateral`) times the leverage the account set for the market: `100 / initial_margin_fraction` (percent). A market the account never configured uses the venue default, `default_initial_margin_fraction` (basis points). On a unified account, resting spot orders do not reduce it: a perp order needing more margin than the unlocked remainder still filled.


# %%
async def available_notional(market_id: str, /):
  """Available balance times the market's configured leverage."""
  acct, d = await asyncio.gather(account(), perp_details())
  configured = [
    p['initial_margin_fraction']
    for p in acct['positions']
    if str(p['market_id']) == market_id
  ]
  fraction = (
    percent(configured[0])
    if configured
    else Decimal(d[market_id]['default_initial_margin_fraction']) / 10_000
  )
  free = acct['cross_asset_value'] - acct['cross_initial_margin_requirement']
  return free / fraction


{m: await available_notional(m) for m in MARKETS}


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.
#
# Prices and sizes are scaled with the market's `Scaler` (no rounding: an off-grid value is rejected). `LIMIT` rests good-till-time, `POST_ONLY` is post-only, `MARKET` is the venue's market order with `price` as the worst acceptable price. The SDK id is a fresh `client_order_index` (uint48). Acceptance is not execution: the sequencer can still reject the order, which then shows up as a `canceled-*` status.


# %%
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send a create-order transaction."""
  scaler = await client.scaler(int(market_id))
  qty = Decimal(order['qty'])
  client_index = next_client_index()
  base_amount = scaler.size(abs(qty))
  price = scaler.price(Decimal(order['price']))
  if order['type'] == 'MARKET':
    response = await client.tx.create_order(
      {
        'order_type': 'market',
        'market_index': int(market_id),
        'client_order_index': client_index,
        'base_amount': base_amount,
        'is_ask': qty < 0,
        'price': price,
      }
    )
  else:
    response = await client.tx.create_order(
      {
        'order_type': 'limit',
        'market_index': int(market_id),
        'client_order_index': client_index,
        'base_amount': base_amount,
        'is_ask': qty < 0,
        'price': price,
        'time_in_force': 'post-only'
        if order['type'] == 'POST_ONLY'
        else 'good-till-time',
      }
    )
  return OrderResponse(id=str(client_index), details=response)


# A resting LIMIT and POST_ONLY buy well below the market, then an off-grid price.
bid = (await depth(ETH, levels=1)).best_bid.price
resting = await place_order(
  ETH,
  {
    'type': 'LIMIT',
    'qty': Decimal('0.0100'),
    'price': (bid * Decimal('0.9')).quantize(Decimal('0.01')),
  },
)
maker = await place_order(
  ETH,
  {
    'type': 'POST_ONLY',
    'qty': Decimal('0.0100'),
    'price': (bid * Decimal('0.9')).quantize(Decimal('0.01')),
  },
)
try:
  off_grid: Any = await place_order(
    ETH, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': Decimal('1000.001')}
  )
except Exception as e:
  off_grid = f'{type(e).__name__}: {e}'
await asyncio.sleep(3)
{
  'placed': (resting.id, maker.id),
  'query': [await query_order(ETH, resting.id), await query_order(ETH, maker.id)],
  'open_orders': [o.id for o in await open_orders(ETH)],
  'off_grid': off_grid,
}


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Cancel by client order index."""
  return await client.tx.cancel_order(market_index=int(market_id), order_index=int(id))


# A cancelled order leaves the active set before `accountOrders` indexes it as inactive: in
# between, `query_order` finds nothing. Measure that gap.
await cancel_order(ETH, resting.id)
sent = time.monotonic()
lookups: list[tuple[float, str | None]] = []
cancelled = None
while time.monotonic() - sent < 30:
  cancelled = await query_order(ETH, resting.id)
  lookups.append(
    (
      round(time.monotonic() - sent, 1),
      cancelled.details['status'] if cancelled else None,
    )
  )
  if cancelled is not None and not cancelled.active:
    break
  await asyncio.sleep(1)
{
  'lookups': lookups,
  'open_orders': [o.id for o in await open_orders(ETH)],
}


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """One cancel transaction per order."""
  return await asyncio.gather(*[cancel_order(market_id, id) for id in ids])


low = (bid * Decimal('0.8')).quantize(Decimal('0.01'))
pair = [
  await place_order(ETH, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': low})
  for _ in range(2)
]
await asyncio.sleep(3)
opened = [o.id for o in await open_orders(ETH)]
await cancel_orders(ETH, [maker.id] + [p.id for p in pair])
await asyncio.sleep(3)
{'before': opened, 'after': [o.id for o in await open_orders(ETH)]}


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """The venue's cancel-all, scoped to one market."""
  return await client.tx.cancel_all_orders(
    {'mode': 'immediate', 'market_index': int(market_id)}
  )


# Two ETH orders and one BTC order: only ETH's are cancelled.
eth_orders = [
  await place_order(ETH, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': low})
  for _ in range(2)
]
btc_bid = (await depth('4096', levels=1)).best_bid.price
btc_order = await place_order(
  '4096',
  {
    'type': 'LIMIT',
    'qty': Decimal('0.00020'),
    'price': (btc_bid * Decimal('0.8')).quantize(Decimal('0.1')),
  },
)
await asyncio.sleep(3)
opened = {m: [o.id for o in await open_orders(m)] for m in (ETH, '4096')}
await cancel_open_orders(ETH)
await asyncio.sleep(3)
remaining = {m: [o.id for o in await open_orders(m)] for m in (ETH, '4096')}
await cancel_open_orders('4096')
{'before': opened, 'after ETH cancel-all': remaining}


# %% [markdown]
# ## Fills
#
# Fee check: a fill between the two accounts (the counterparty rests, the account takes); each account's USDC margin balance moves by exactly the mapped fee (the position is opened, so no PnL is realized). Then the position is sold back at market while `trades_stream` is open.

# %%
fee_qty = Decimal('0.0100')


async def trade_ids(c: Lighter) -> set[str]:
  """Ids of the account's latest ETH trades."""
  page = await c.api.account.orders.trades(
    'timestamp', limit=50, account_index=c.signer.account_index, market_id=int(ETH)
  )
  return {t['trade_id_str'] for t in page['trades']}


async def check(c: Lighter, known: set[str], before: Decimal) -> dict[str, Any]:
  """Mapped fees of the account's new fills against its USDC balance change.

  Trades are indexed seconds after the balance moves (and stamped with their block's time,
  which precedes execution), so new fills are told apart by id and awaited.
  """
  account_index = c.signer.account_index
  fills: list[Trade] = []
  change = Decimal(0)
  for _ in range(20):
    page = await c.api.account.orders.trades(
      'timestamp', limit=50, account_index=account_index, market_id=int(ETH)
    )
    fills = [
      parse_trade(t, account_index)
      for t in page['trades']
      if t['trade_id_str'] not in known
    ]
    change = before - await usdc_margin(c)
    if fills and sum((f.fee.amount for f in fills if f.fee), Decimal(0)) == change:
      break
    await asyncio.sleep(2)
  return {
    'fills': [
      (
        f.qty,
        f.price,
        'maker' if f.maker else 'taker',
        f.details.get('maker_fee' if f.maker else 'taker_fee'),
      )
      for f in fills
    ],
    'mapped_fees': sum((f.fee.amount for f in fills if f.fee), Decimal(0)),
    'balance_change': change,
  }


known = (await trade_ids(client), await trade_ids(counterparty))
before = (await usdc_margin(client), await usdc_margin(counterparty))
price = await crossing_price(ETH, sell=True)
await post_only(counterparty, ETH, -fee_qty, price)
await asyncio.sleep(2)
await place_order(
  ETH,
  {
    'type': 'MARKET',
    'qty': fee_qty,
    'price': (price * Decimal('1.01')).quantize(price),
  },
)  # noqa: F821 -- defined in `place_order` above
await asyncio.sleep(2)
await counterparty.tx.cancel_all_orders({'mode': 'immediate', 'market_index': int(ETH)})
{
  'taker (account)': await check(client, known[0], before[0]),
  'maker (counterparty)': await check(counterparty, known[1], before[1]),
}

# %%
# Sell back what the fee check bought, streaming the fill.
await fill_while_streaming(ETH, -fee_qty)


# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}):
  """The market's `index_price` from `orderBookDetails`."""
  details = await client.api.markets.order_book_details(int(market_id))
  return (details['order_book_details'] or [])[0]['index_price']


{m: await index(m) for m in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.
#
# `market_stats` carries `current_funding_rate`, the venue's estimate of the next payment's rate (percent, positive when longs pay), and `funding_timestamp`, the last settlement. The next settlement is the following hour.


# %%
def next_settlement(last: datetime) -> datetime:
  """The hour after the last settlement (whose stamp carries a few ms of jitter)."""
  return last.replace(minute=0, second=0, microsecond=0) + FUNDING_INTERVAL


async def next_funding(market_id: str, /) -> NextFunding:
  """The predicted rate of the next hourly settlement."""
  s = (await all_stats())[market_id]
  return NextFunding(
    rate=percent(s['current_funding_rate']),
    time=next_settlement(s['funding_timestamp']),
    interval=FUNDING_INTERVAL,
    premium=percent(s['premium']),
  )


{m: await next_funding(m) for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.
#
# Prices and funding from `market_stats:all`; open interest from `orderBookDetails`, which reports it in base units (`market_stats` reports USDC).


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Index, mark, predicted funding and base-unit open interest."""
  stats, d = await asyncio.gather(all_stats(), perp_details())
  wanted = stats.keys() if markets is None else [m for m in markets if m in stats]
  return {
    m: PerpStats(
      index=stats[m]['index_price'],
      mark=stats[m]['mark_price'],
      funding=percent(stats[m]['current_funding_rate']),
      next_funding_time=next_settlement(stats[m]['funding_timestamp']),
      funding_interval=FUNDING_INTERVAL,
      open_interest=Decimal(str(d[m]['open_interest'])),
    )
    for m in wanted
  }


{
  'all': len(await perp_stats()),
  'selected': await perp_stats(MARKETS),
  'empty': await perp_stats([]),
}


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.
#
# `fundings` at `1h` resolution. The venue's `rate` is unsigned, in percent, with `direction` naming the side that paid: `long` maps to a positive SDK rate, `short` to a negative one (mainnet samples of both directions are in the probe below). The venue treats both bounds as exclusive and at whole-hour granularity (`[15:59:59.999, 18:00:00.001]` returns only `17:00`), so the request is widened by one interval on each side and the SDK's inclusive bounds are applied locally.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Hourly settlements with `start <= time <= end`."""
  d = (await perp_details())[market_id]
  lower = start or d['created_at']
  upper = end or datetime.now(timezone.utc)
  pages = client.api.markets.fundings_paged(
    market_id=int(market_id),
    resolution='1h',
    start_timestamp=lower - FUNDING_INTERVAL,
    end_timestamp=upper + FUNDING_INTERVAL,
    count_back=0,
  )
  async for page in pages:
    yield [
      FundingRate(
        rate=percent(f['rate']) if f['direction'] == 'long' else -percent(f['rate']),
        time=f['timestamp'],
      )
      for f in page
      if lower <= f['timestamp'] <= upper
    ]


rates = {
  m: [r async for page in funding_rates(m, end - timedelta(days=2), end) for r in page]
  for m in MARKETS
}
bounded_lower = rates[ETH][2].time
bounded = [
  r
  async for page in funding_rates(
    ETH, bounded_lower, bounded_lower + timedelta(hours=2)
  )
  for r in page
]
{
  'counts': {m: len(rs) for m, rs in rates.items()},
  'latest': {m: rs[-1] if rs else None for m, rs in rates.items()},
  'inclusive_bounds': [r.time for r in bounded],
  'all_history': len([r async for page in funding_rates(ETH) for r in page]),
}

# %%
# Direction sign check on mainnet (public): `short` rows exist and carry unsigned rates.
async with Lighter.new(public=True) as mainnet:
  window_end = datetime.now(timezone.utc)
  rows = await mainnet.api.markets.fundings(
    market_id=0,
    resolution='1h',
    start_timestamp=window_end - timedelta(days=10),
    end_timestamp=window_end,
    count_back=0,
  )
by_direction: dict[str, list[Decimal]] = {}
for f in rows['fundings']:
  by_direction.setdefault(f['direction'], []).append(f['rate'])
{k: (len(v), min(v), max(v)) for k, v in by_direction.items()}


# %% [markdown]
# ## `funding_payments`
#
# Fetch personal funding payments for one market or the whole exchange.
#
# `position_funding`, newest first. The venue's `change` is received-positive; the SDK's amount is paid-positive, so it is negated. The exchange-wide form omits `market_ids`. The request window is widened by one interval, as for `funding_rates`, and the inclusive bounds are applied locally.


# %%
FUNDING_PAGE = 100


async def funding_payments(
  market_id: str | None, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal funding payments with `start <= time <= end`."""
  pages = client.api.account.position_funding_paged(
    account_index=ACCOUNT,
    limit=FUNDING_PAGE,
    start_timestamp=start - FUNDING_INTERVAL,
    end_timestamp=end + FUNDING_INTERVAL,
    market_ids=None if market_id is None else [int(market_id)],
  )
  async for page in pages:
    rows: list[FundingPayment] = []
    for f in page:
      if not start <= f['timestamp'] <= end:
        continue
      if market_id is None:
        rows.append(
          ExchangeFundingPayment(
            amount=-f['change'], time=f['timestamp'], market_id=str(f['market_id'])
          )
        )
      else:
        rows.append(FundingPayment(amount=-f['change'], time=f['timestamp']))
    if rows:
      yield rows


payments_start = end - timedelta(days=30)
payments = {
  m: [p async for page in funding_payments(m, payments_start, end) for p in page]
  for m in MARKETS
}
exchange_payments = [
  p async for page in funding_payments(None, payments_start, end) for p in page
]
settled = payments[ETH][0].time if payments[ETH] else end
exact = [p async for page in funding_payments(ETH, settled, settled) for p in page]
{
  'per_market': {m: (len(ps), ps[:2]) for m, ps in payments.items()},
  'exchange': (len(exchange_payments), exchange_payments[:2]),
  'exact_bounds': exact,
}


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.
#
# `position` is unsigned with `sign` beside it; a market the account never traded has no entry and is flat.


# %%
async def perp_position(market_id: str, /) -> PerpPosition:
  """The account's signed position and average entry."""
  for p in (await account())['positions']:
    if str(p['market_id']) == market_id:
      return PerpPosition(
        size=p['position'] * p['sign'], entry_price=p['avg_entry_price']
      )
  return PerpPosition()


{m: await perp_position(m) for m in MARKETS}


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Defers to `perp_collateral`."""
  return await perp_collateral(market_id)


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.
#
# **Cross** (the exchange, and any market held cross): the account's own figures, `cross_asset_value` (equity), `cross_initial_margin_requirement` and `cross_maintenance_margin_requirement`; free is equity minus the initial requirement, which equals `user_stats.cross_stats.available_balance`. The account's `available_balance` is not the cross figure: it adds every isolated bucket's free margin. Leverage is the SDK's definition, cross position value over equity.
#
# **Isolated** (a market whose position has `margin_mode == 1`): the account reports the bucket's parts, not its totals. Equity is `allocated_margin + unrealized_pnl`; the requirements are the position value times the position's `initial_margin_fraction` (percent) and the market's `maintenance_margin_fraction` (basis points); free is equity minus the initial requirement. The cell below checks each against the venue: `user_stats`' total minus cross figures give the equity; the maintenance requirement reproduces the venue's `liquidation_price`; and `update_margin` removals succeed just below the free figure and are rejected just above it.


# %%
def cross_bucket(acct: DetailedAccount) -> PerpCollateral:
  """The cross-margin bucket, straight from the account."""
  equity = acct['cross_asset_value']
  notional = sum(
    (abs(p['position_value']) for p in acct['positions'] if p['margin_mode'] == 0),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=equity - acct['cross_initial_margin_requirement'],
    initial_margin=acct['cross_initial_margin_requirement'],
    maintenance_margin=acct['cross_maintenance_margin_requirement'],
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


def isolated_bucket(p: AccountPosition, d: PerpsOrderBookDetail) -> PerpCollateral:
  """One isolated position's bucket, from its allocated margin and the margin fractions."""
  notional = abs(p['position_value'])
  equity = p['allocated_margin'] + p['unrealized_pnl']
  initial = notional * percent(p['initial_margin_fraction'])
  return PerpCollateral(
    equity=equity,
    free_collateral=max(equity - initial, Decimal(0)),
    initial_margin=initial,
    maintenance_margin=notional * d['maintenance_margin_fraction'] / 10_000,
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='isolated',
  )


async def perp_collateral_of(
  c: Lighter, market_id: str | None = None
) -> PerpCollateral:
  """The bucket backing `market_id` (cross when `None`) for the account of `c`."""
  acct, d = await asyncio.gather(account(c), perp_details())
  for p in acct['positions']:
    if (
      market_id is not None
      and str(p['market_id']) == market_id
      and p['margin_mode'] == 1
    ):
      return isolated_bucket(p, d[market_id])
  return cross_bucket(acct)


async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  """The bucket backing `market_id`, cross when `None`."""
  return await perp_collateral_of(client, market_id)


async def venue_stats(c: Lighter):
  """The venue's own `user_stats` figures."""
  async with c.streams.user_stats(c.signer.account_index) as stream:
    async for frame in stream:
      return frame['stats']
  raise RuntimeError('user_stats stream closed before its snapshot')


stats = await venue_stats(client)
{
  'exchange': await perp_collateral(),
  'ETH': await perp_collateral(ETH),
  'venue_cross_stats': stats['cross_stats'],
}

# %%
# Isolated: the counterparty opens a 10x isolated ETH long with 20 USDC of extra margin. A margin-mode change
# needs the market flat and without orders, so the counterparty is flattened first.


async def flatten(c: Lighter, market_id: str):
  """Cancel `c`'s orders on the market and close its position at market."""
  await c.tx.cancel_all_orders({'mode': 'immediate', 'market_index': int(market_id)})
  held = next(
    (p for p in (await account(c))['positions'] if str(p['market_id']) == market_id),
    None,
  )
  if held is not None and held['position'] != 0:
    book = await depth(market_id, levels=1)
    sell = held['sign'] > 0
    worst = (
      book.best_bid.price * Decimal('0.98')
      if sell
      else book.best_ask.price * Decimal('1.02')
    )
    scaler = await c.scaler(int(market_id))
    await c.tx.create_order(
      {
        'order_type': 'market',
        'market_index': int(market_id),
        'client_order_index': next_client_index(),
        'base_amount': scaler.size(held['position']),
        'is_ask': sell,
        'price': scaler.price(worst, rounding='floor' if sell else 'ceiling'),
      }
    )
  await asyncio.sleep(3)


await flatten(counterparty, ETH)
await counterparty.tx.update_leverage(
  market_index=int(ETH), initial_margin_fraction=1000, margin_mode='isolated'
)
await asyncio.sleep(2)
ask = (await depth(ETH, levels=1)).best_ask.price
await counterparty.tx.create_order(
  {
    'order_type': 'market',
    'market_index': int(ETH),
    'client_order_index': next_client_index(),
    'base_amount': (await counterparty.scaler(int(ETH))).size(Decimal('0.0200')),
    'is_ask': False,
    'price': (await counterparty.scaler(int(ETH))).price(
      ask * Decimal('1.02'), rounding='ceiling'
    ),
  }
)
await asyncio.sleep(3)
await counterparty.tx.update_margin(
  market_index=int(ETH), usdc_amount=20 * 10**6, direction='add'
)
await asyncio.sleep(3)

iso_acct, iso_stats = await account(counterparty), await venue_stats(counterparty)
iso_position = next(p for p in iso_acct['positions'] if str(p['market_id']) == ETH)
iso = await perp_collateral_of(counterparty, ETH)
cross = await perp_collateral_of(counterparty)
size = iso_position['position'] * iso_position['sign']
mmf = Decimal(details[ETH]['maintenance_margin_fraction']) / 10_000
# Liquidation where equity == maintenance: allocated + size * (P - entry) == |size| * P * mmf.
liquidation = (
  size * iso_position['avg_entry_price'] - iso_position['allocated_margin']
) / (size - abs(size) * mmf)


async def remove_margin(amount: Decimal) -> str:
  """Try to remove `amount` from the isolated position; returns what the sequencer did."""
  before = (await account(counterparty))['positions']
  allocated = next(p['allocated_margin'] for p in before if str(p['market_id']) == ETH)
  try:
    await counterparty.tx.update_margin(
      market_index=int(ETH),
      usdc_amount=int(amount.quantize(Decimal('0.000001')) * 10**6),
      direction='remove',
    )
  except Exception as e:
    return f'rejected: {e}'
  await asyncio.sleep(3)
  after = next(
    p['allocated_margin']
    for p in (await account(counterparty))['positions']
    if str(p['market_id']) == ETH
  )
  return 'executed' if after != allocated else 'not executed'


free_now = (await perp_collateral_of(counterparty, ETH)).free_collateral
{
  'isolated': iso,
  'cross': cross,
  'equity_vs_user_stats': (
    iso.equity,
    iso_stats['portfolio_value'] - iso_stats['cross_stats']['portfolio_value'],
  ),
  'liquidation_vs_venue': (
    liquidation,
    iso_position['liquidation_price'],
    abs(liquidation / iso_position['liquidation_price'] - 1),
  ),
  'cross_free_vs_user_stats': (
    cross.free_collateral,
    iso_stats['cross_stats']['available_balance'],
    iso_acct['available_balance'],
  ),
  'remove free + 0.05': await remove_margin(free_now + Decimal('0.05')),
  'remove free - 0.05': await remove_margin(free_now - Decimal('0.05')),
}

# %%
# Close the counterparty's isolated position and restore cross margin.
bid = (await depth(ETH, levels=1)).best_bid.price
await counterparty.tx.create_order(
  {
    'order_type': 'market',
    'market_index': int(ETH),
    'client_order_index': next_client_index(),
    'base_amount': (await counterparty.scaler(int(ETH))).size(abs(size)),
    'is_ask': True,
    'price': (await counterparty.scaler(int(ETH))).price(
      bid * Decimal('0.98'), rounding='floor'
    ),
  }
)
await asyncio.sleep(3)
await counterparty.tx.update_leverage(
  market_index=int(ETH), initial_margin_fraction=500, margin_mode='cross'
)
await asyncio.sleep(2)
[
  (p['position'], p['margin_mode'])
  for p in (await account(counterparty))['positions']
  if str(p['market_id']) == ETH
]

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | Numeric market ids from `orderBookDetails(filter='perp')` (typed-lighter 0.2.0 types the other list as nullable). |
# | `depth` | verified | `orderBookOrders` summed per price; equals the WS snapshot on testnet. Capped at 250 orders/side (188 levels on mainnet ETH against 1053/659 in the WS book); a full side drops its possibly-partial last level. |
# | `depth_stream` | verified | `order_book` snapshot plus 50 ms deltas; `begin_nonce`/`nonce` continuity checked. |
# | `tickers` | verified | `market_stats:all`. `bid_qty`/`ask_qty` are `None`: no size at the best levels. Volumes pass through `float` (see issues). |
# | `rules` | verified | Signing scales, `min_base_amount`/`min_quote_amount`, standard-account fees (0%), `fee_asset` `'3'` (USDC), `api` from `status`. |
# | `fees` | verified | `account/limits` fee ticks in ppm: `plus` 50/50, `premium` 40/280, as the docs' tiers; fills charge exactly these rates. |
# | `candles` | verified | All six intervals, walked in grid-aligned windows whose `count_back` defeats the CDN cache (no `candles_paged` since typed-lighter 0.2.0); half-open bounds, a 1200-row walk (500/500/200), and on mainnet a 550h walk after a 72h one with the same end and an unaligned 5m start all checked. |
# | `query_order` | verified | By `client_order_index`. A cancelled order is missing from `accountOrders` for ~10 s (out of the active set, not yet indexed inactive): `None` in that window. Inactive orders are kept 24 h. |
# | `open_orders` | verified | Live orders placed and cancelled in the trading cells. |
# | `trades_history` | verified | Per market and exchange-wide; fee = `usd_amount` x the role's tick, equal to the balance change for taker (280) and maker (40) fills. `time` is the trade's block `timestamp`, which precedes `transaction_time` by up to ~20 s. |
# | `trades_stream` | verified | `account_market`; a live market sell was streamed with its fee. |
# | `position` | verified | Defers to `perp_position`. |
# | `available_notional` | verified | Free cross collateral times the market's configured leverage (`initial_margin_fraction`, else the default). |
# | `place_order` | verified | LIMIT (GTT), POST_ONLY and MARKET placed live; off-grid prices raise before signing. |
# | `cancel_order` | verified | By client index; status `canceled` once indexed. |
# | `cancel_orders` | verified | One cancel per order; three cancelled. |
# | `cancel_open_orders` | verified | Venue cancel-all scoped to the market; another market's order survived. |
# | `index` | verified | `orderBookDetails` `index_price`. |
# | `next_funding` | verified | `market_stats` `current_funding_rate` (percent) and `premium`; time is the hour after `funding_timestamp`. |
# | `perp_stats` | verified | Index, mark and funding from `market_stats:all`; base-unit open interest from `orderBookDetails` (through `float`, see issues). |
# | `funding_rates` | verified | Hourly `fundings`, signed by `direction`; inclusive bounds applied locally over a widened request (the venue's are exclusive and hour-granular). |
# | `funding_payments` | verified | `position_funding`, per market and exchange-wide; `change` negated to paid-positive; exact-bound query returns the payment. |
# | `perp_position` | verified | Signed from `position` and `sign`; the account holds a live ETH long. |
# | `collateral` | verified | Defers to `perp_collateral`. |
# | `perp_collateral` | verified | Cross: account figures, free = equity - IM (= `user_stats` cross available; the account's `available_balance` adds isolated free margin). Isolated: allocated + uPnL, IMF/MMF requirements; equity matches `user_stats`, MM reproduces `liquidation_price` (to 4e-6 relative across runs, exactly in the last), free bounds `update_margin` removals. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them. These are testnet ids; only mainnet instruments are catalogued.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets=set(listed), assets={USDC})
gap('lighter', ids, load_catalogue())

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
