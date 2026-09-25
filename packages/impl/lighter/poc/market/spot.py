# %% [markdown]
# # lighter `market` PoC (spot)
#
# Maps `typed_lighter` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Runs against Lighter's **testnet** (`LIGHTER_TESTNET_*` credentials): spot markets ETH/USDC and LIT/USDC. IDs are the venue's numeric ids as decimal strings: market ids are `market_id` (`'4098'` is testnet ETH/USDC), asset ids are `asset_id` (`'1'` ETH, `'2'` LIT, `'3'` USDC). The book, candle, order and trade mappings are the perp script's (`perp.py`), which documents their venue behaviour; this script re-runs them on spot markets and maps what differs: fees in the received asset, and collateral by account mode.
#
# The sub-account (`LIGHTER_TESTNET_SUB_*`) is the counterparty for fills (testnet spot books are one-sided) and is switched to classic mode for the collateral check.

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
from typed_lighter.api.markets.order_book_details import SpotOrderBookDetail
from typed_lighter.schemas import (
  AccountAsset,
  Candle as LighterCandle,
  Order as LighterOrder,
  PriceLevel,
  SimpleOrder,
  SpotMarketStats,
  Trade as LighterTrade,
)

from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  ExchangeTrade,
  Fees,
  Order,
  OrderResponse,
  OrderState,
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

MARKETS = ['4098', '4099']
ETH_USDC = '4098'
FEE_TICK = Decimal('1e-6')
"""Fee ticks are parts per million (see `perp.py`)."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


async def spot_details() -> dict[str, SpotOrderBookDetail]:
  """Every spot market's details, keyed by market id (the other type's list is `null`)."""
  details = await client.api.markets.order_book_details(filter='spot')
  return {str(d['market_id']): d for d in details['spot_order_book_details'] or []}


async def all_stats() -> dict[str, SpotMarketStats]:
  """The `spot_market_stats:all` snapshot, keyed by market id."""
  async with client.streams.spot_market_stats('all') as stream:
    async for frame in stream:
      stats = frame['spot_market_stats']
      rows = stats.values() if isinstance(stats, dict) else [stats]
      return {str(s['market_id']): s for s in rows}  # type: ignore[union-attr]
  raise RuntimeError('spot_market_stats stream closed before its snapshot')


details = await spot_details()
assets = {
  str(a['asset_id']): a['symbol']
  for a in (await client.api.markets.asset_details())['asset_details']
}
(
  version('typed-lighter'),
  ACCOUNT,
  SUB,
  {m: d['symbol'] for m, d in details.items()},
  assets,
)

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
    grep=r'^api\.markets\.|^api\.account\.(get|limits|orders\.)|^streams\.(order_book|spot_market_stats|account_market)|^tx\.(create_order|cancel_order|cancel_all_orders|update_account_config|transfer)',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """Every spot market id, inactive ones included."""
  return list(await spot_details())


listed = await markets()
assert set(MARKETS) <= set(listed)
{
  m: (
    details[m]['symbol'],
    details[m]['status'],
    details[m]['base_asset_id'],
    details[m]['quote_asset_id'],
  )
  for m in listed
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book. Same mapping as perp: `orderBookOrders` summed per price.

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
{m: (len(b.bids), len(b.asks), b.bids[:1], b.asks[:1]) for m, b in books.items()}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book. Same mapping as perp: the `order_book` channel serves spot markets too.


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


async def first_books(market_id: str, *, count: int, timeout: float):
  """Up to `count` books, stopping early when no update arrives within `timeout` seconds."""
  seen: list[tuple[int, int]] = []
  async with depth_stream(market_id, levels=10) as stream:
    it = aiter(stream)
    try:
      while len(seen) < count:
        book = await asyncio.wait_for(anext(it), timeout)
        seen.append((len(book.bids), len(book.asks)))
    except asyncio.TimeoutError:
      pass
  return seen


{m: await first_books(m, count=3, timeout=10) for m in MARKETS}


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.
#
# `spot_market_stats:all` carries last price, best bid/ask and 24h volumes; no size at the best levels.


# %%
def price_or_none(value: Decimal | Literal['']) -> Decimal | None:
  """A stats price, or `None` where the venue sends `""` (missing)."""
  return None if value == '' else value


async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Tickers from the `spot_market_stats:all` snapshot."""
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
# As for perps, except the fee asset: Lighter charges spot fees in the *received* asset, base on a buy and quote on a sell (the fills below show it), which one `fee_asset` cannot express. It is `None` here: the fee asset depends on the fill (ADR 0028).


# %%
def percent(value: Decimal) -> Decimal:
  """A venue percentage as a fraction."""
  return value / 100


def standard_fees(d: SpotOrderBookDetail) -> Fees:
  """The market's standard-account rates; a disabled fee is zero."""
  maker = percent(d['maker_fee']) if d['is_maker_fee_enabled'] else Decimal(0)
  taker = percent(d['taker_fee']) if d['is_taker_fee_enabled'] else Decimal(0)
  return Fees.symmetric(maker=maker, taker=taker)


async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Precision, size and notional floors and standard fees from `orderBookDetails`."""
  d = (await spot_details())[market_id]
  return Rules(
    fee_asset=None,
    tick_size=Decimal(1).scaleb(-d['supported_price_decimals']),
    step_size=Decimal(1).scaleb(-d['supported_size_decimals']),
    fixed_min_qty=d['min_base_amount'],
    min_value=d['min_quote_amount'],
    fees=standard_fees(d),
    api=d['status'] == 'active',
    details={
      'symbol': d['symbol'],
      'base_asset_id': d['base_asset_id'],
      'quote_asset_id': d['quote_asset_id'],
      'order_quote_limit': d['order_quote_limit'],
      'multiplier': d['multiplier'],
    },
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback. As for perps: `account/limits`' fee ticks, which spot fills carry too.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """The account's current maker/taker ticks."""
  limits = await client.api.account.limits(ACCOUNT)
  return Fees.symmetric(
    maker=limits['current_maker_fee_tick'] * FEE_TICK,
    taker=limits['current_taker_fee_tick'] * FEE_TICK,
  )


await fees(ETH_USDC)


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles. Same mapping as perp: grid-aligned windows, each sending its own number of opens as `count_back` (the venue's CDN keys `candles` without the start).

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
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Candles opening in `[start, end)`, one window per request."""
  width = candle_width(interval)
  for lower, upper in candle_windows(start, end, interval, size=500):
    offset = (lower - EPOCH) % width
    lower = lower if not offset else lower - offset + width
    count = -((lower - upper) // width)
    if count <= 0:
      continue
    response = await client.api.markets.candles(
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


candle_end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
{
  m: {
    interval: len(
      [
        c
        async for page in candles(
          m, interval, candle_end - timedelta(days=2), candle_end
        )
        for c in page
      ]
    )
    for interval in ('15m', '1h', '4h')
  }
  for m in MARKETS
} | {
  'sample': [
    c
    async for page in candles(
      ETH_USDC, '1h', candle_end - timedelta(hours=3), candle_end
    )
    for c in page
  ]
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID. Same mapping as perp: the id is the `client_order_index`. Exercised on live orders in the trading cells below.

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


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


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
# Fetch personal fills for one market or the whole exchange. Same mapping as perp, with `market_type='spot'`, except the fee: it is charged in the asset the account received, the base asset on a buy and the quote asset on a sell, at the trade's tick for the account's role times the amount received. The fills below match the balance changes exactly.

# %%
TRADES_PAGE = 100


def parse_trade(t: LighterTrade, account: int = ACCOUNT) -> Trade:
  """The account's fill from a venue trade, with its fee in the received asset."""
  d = details[str(t['market_id'])]
  is_ask = t['ask_account_id'] == account
  maker = t['is_maker_ask'] == is_ask
  tick = (t.get('maker_fee', 0) if maker else t.get('taker_fee', 0)) * FEE_TICK
  fee = (
    Trade.Fee(amount=t['size'] * t['price'] * tick, asset=str(d['quote_asset_id']))
    if is_ask
    else Trade.Fee(amount=t['size'] * tick, asset=str(d['base_asset_id']))
  )
  return Trade(
    id=t['trade_id_str'],
    price=t['price'],
    qty=-t['size'] if is_ask else t['size'],
    time=t['timestamp'],
    maker=maker,
    fee=fee,
    details=t,
  )


async def trades_history(
  market_id: str | None, /, start: datetime, end: datetime
) -> AsyncIterable[Sequence[Trade]]:
  """Personal spot fills with `start <= time <= end`, newest first."""
  pages = client.api.account.orders.trades_paged(
    'timestamp',
    limit=TRADES_PAGE,
    account_index=ACCOUNT,
    market_type='spot',
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
  'exchange': len(exchange_wide),
  'exchange_equals_union': sorted(t.id or '' for t in exchange_wide)
  == sorted(t.id or '' for ts in by_market.values() for t in ts),
}


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades. Same mapping as perp: `account_market` serves spot markets too. Exercised on a live fill in the fills section below.


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


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.
#
# The account's balance of the base asset (`assets[].balance`, locked part included), in either account mode.


# %%
async def account(c: Lighter = client) -> DetailedAccount:
  """The account's details."""
  accounts = await c.api.account.get({'by': 'index', 'value': c.signer.account_index})
  return accounts['accounts'][0]


def balance_of(acct: DetailedAccount, asset_id: int) -> AccountAsset | None:
  """The account's balance row of one asset, if it holds any."""
  return next((a for a in acct['assets'] if a['asset_id'] == asset_id), None)


async def position(market_id: str, /) -> Position:
  """The base asset's balance."""
  row = balance_of(await account(), details[market_id]['base_asset_id'])
  return Position(size=row['balance'] if row else Decimal(0))


{m: await position(m) for m in MARKETS}


# %% [markdown]
# ## `collateral`
#
# Fetch collateral.
#
# The quote asset's balance, which depends on the account mode (`account_trading_mode`), as measured with orders that were accepted just below and rejected just above each figure:
#
# - **classic** (`0`): spot and perps are separate. The spot balance is `balance`; resting bids lock `locked_balance` of it. A spot bid with no spot USDC is rejected (`not enough asset balance`) whatever the perps side holds.
# - **unified** (`1`): a margin-enabled quote asset (USDC) lives in `margin_balance`, shared with perps, and its spot `balance` is `0`. Resting spot bids still lock `locked_balance`, but `available_balance` does not reflect those locks: a spot bid can spend `available_balance - locked_balance` (perps' initial margin reduces it), while perps can still use all of `available_balance`.


# %%
def collateral_of(acct: DetailedAccount, quote_asset_id: int) -> Collateral:
  """The quote asset's spot collateral, by account mode."""
  row = balance_of(acct, quote_asset_id)
  if row is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  if acct['account_trading_mode'] == 1 and row['margin_mode'] == 'enabled':
    return Collateral(
      equity=row['margin_balance'],
      free_collateral=max(
        acct['available_balance'] - row['locked_balance'], Decimal(0)
      ),
    )
  return Collateral(
    equity=row['balance'], free_collateral=row['balance'] - row['locked_balance']
  )


async def collateral(market_id: str | None = None, /) -> Collateral:
  """The market's quote asset collateral."""
  if market_id is None:
    raise NotImplementedError('Spot collateral is per quote asset: pass a market')
  return collateral_of(await account(), details[market_id]['quote_asset_id'])


{m: await collateral(m) for m in MARKETS}


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open: the free quote balance, per the SDK contract for spot.


# %%
async def available_notional(market_id: str, /):
  """Free quote balance."""
  return (await collateral(market_id)).free_collateral


{m: await available_notional(m) for m in MARKETS}


# %% [markdown]
# ## `place_order`
#
# Place an order in the market. Same mapping as perp.


# %%
def next_client_index() -> int:
  """A fresh client order index: microseconds since the epoch, modulo 2^48."""
  return time.time_ns() // 1000 % 2**48


async def create(c: Lighter, market_id: str, order: Order) -> OrderResponse:
  """Sign and send a create-order transaction for the account of `c`."""
  scaler = await c.scaler(int(market_id))
  qty = Decimal(order['qty'])
  client_index = next_client_index()
  base_amount = scaler.size(abs(qty))
  price = scaler.price(Decimal(order['price']))
  if order['type'] == 'MARKET':
    response = await c.tx.create_order(
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
    response = await c.tx.create_order(
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


async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send a create-order transaction."""
  return await create(client, market_id, order)


async def query_until(market_id: str, id: str, *, active: bool) -> OrderState | None:
  """Poll `query_order` until the order shows the wanted `active` state (the order index lags)."""
  for _ in range(20):
    state = await query_order(market_id, id)
    if state is not None and state.active == active:
      return state
    await asyncio.sleep(1)
  return None


# A resting LIMIT and POST_ONLY buy below the market.
low = Decimal('1000.00')
resting = await place_order(
  ETH_USDC, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': low}
)
maker = await place_order(
  ETH_USDC, {'type': 'POST_ONLY', 'qty': Decimal('0.0100'), 'price': low}
)
{
  'query': [
    await query_until(ETH_USDC, resting.id, active=True),
    await query_until(ETH_USDC, maker.id, active=True),
  ],
  'open_orders': [o.id for o in await open_orders(ETH_USDC)],
  'collateral': await collateral(ETH_USDC),
}


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Cancel by client order index."""
  return await client.tx.cancel_order(market_index=int(market_id), order_index=int(id))


await cancel_order(ETH_USDC, resting.id)
cancelled = await query_until(ETH_USDC, resting.id, active=False)
{
  'cancelled': cancelled.details['status'] if cancelled else None,
  'open_orders': [o.id for o in await open_orders(ETH_USDC)],
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


pair = [
  await place_order(ETH_USDC, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': low})
  for _ in range(2)
]
await asyncio.sleep(3)
opened = [o.id for o in await open_orders(ETH_USDC)]
await cancel_orders(ETH_USDC, [maker.id] + [p.id for p in pair])
await asyncio.sleep(3)
{'before': opened, 'after': [o.id for o in await open_orders(ETH_USDC)]}


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.
#
# The venue's cancel-all scoped to a market (`CancelAllNow.market_index`) works on perps but rejects spot markets (`21619 invalid market type`), so each open order is cancelled instead.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Cancel each open order: the venue's market-scoped cancel-all rejects spot markets."""
  return await cancel_orders(market_id, [o.id for o in await open_orders(market_id)])


try:
  await client.tx.cancel_all_orders(
    {'mode': 'immediate', 'market_index': int(ETH_USDC)}
  )
  scoped = 'accepted'
except Exception as e:
  scoped = f'rejected: {e}'


# Two ETH/USDC orders and one LIT/USDC order: only ETH/USDC's are cancelled.
eth_orders = [
  await place_order(ETH_USDC, {'type': 'LIMIT', 'qty': Decimal('0.0100'), 'price': low})
  for _ in range(2)
]
lit_order = await place_order(
  '4099', {'type': 'LIMIT', 'qty': Decimal('1.00'), 'price': Decimal('10.0000')}
)
await asyncio.sleep(3)
opened = {m: [o.id for o in await open_orders(m)] for m in MARKETS}
await cancel_open_orders(ETH_USDC)
await asyncio.sleep(3)
remaining = {m: [o.id for o in await open_orders(m)] for m in MARKETS}
await cancel_open_orders('4099')
{
  'before': opened,
  'after ETH/USDC cancel-all': remaining,
  'venue scoped cancel-all': scoped,
}


# %% [markdown]
# ## Fills
#
# Two fills against the counterparty's resting orders: the account buys ETH as taker (fee in ETH), then sells it back as taker into the counterparty's bid (fee in USDC; the counterparty's maker buy pays in ETH). The sell is taken while `trades_stream` is open. Each account's balances move by exactly the mapped fees.


# %%
async def balances(c: Lighter) -> dict[str, Decimal]:
  """Spot balances by asset id, USDC's margin balance included."""
  acct = await account(c)
  out = {str(a['asset_id']): a['balance'] for a in acct['assets']}
  usdc = balance_of(acct, 3)
  if usdc is not None:
    out['3'] += usdc['margin_balance']
  return out


async def known_ids(c: Lighter) -> set[str]:
  """Ids of the account's latest ETH/USDC trades."""
  page = await c.api.account.orders.trades(
    'timestamp', limit=20, account_index=c.signer.account_index, market_id=int(ETH_USDC)
  )
  return {t['trade_id_str'] for t in page['trades']}


async def new_fills(c: Lighter, known: set[str], *, count: int) -> list[Trade]:
  """The account's ETH/USDC fills not in `known`, awaiting the trades index."""
  rows: list[Trade] = []
  for _ in range(20):
    page = await c.api.account.orders.trades(
      'timestamp',
      limit=20,
      account_index=c.signer.account_index,
      market_id=int(ETH_USDC),
    )
    rows = [
      parse_trade(t, c.signer.account_index)
      for t in page['trades']
      if t['trade_id_str'] not in known
    ]
    if len(rows) >= count:
      break
    await asyncio.sleep(2)
  return rows


def expected(before: dict[str, Decimal], fills: Sequence[Trade]) -> dict[str, Decimal]:
  """Balances after `fills`, net of their mapped fees."""
  out = dict(before)
  for f in fills:
    out['1'] = out.get('1', Decimal(0)) + f.qty
    out['3'] = out.get('3', Decimal(0)) - f.qty * f.price
    if f.fee:
      out[f.fee.asset] -= f.fee.amount
  return out


qty = Decimal('0.0050')
tick = Decimal('0.01')
known = (await known_ids(client), await known_ids(counterparty))
before = (await balances(client), await balances(counterparty))

# Buy: the counterparty rests an ask just inside the book, the account takes it.
ask = (await depth(ETH_USDC, levels=1)).asks[0].price
await create(
  counterparty, ETH_USDC, {'type': 'POST_ONLY', 'qty': -qty, 'price': ask - tick}
)
await asyncio.sleep(2)
await place_order(ETH_USDC, {'type': 'MARKET', 'qty': qty, 'price': ask})

# Sell, streamed: the counterparty rests a bid, the account sells into it.
bid = ask - 20
await create(counterparty, ETH_USDC, {'type': 'POST_ONLY', 'qty': qty, 'price': bid})
await asyncio.sleep(2)
async with trades_stream(ETH_USDC) as stream:
  first = asyncio.ensure_future(anext(aiter(stream)))
  await asyncio.sleep(1)
  await place_order(ETH_USDC, {'type': 'MARKET', 'qty': -qty, 'price': bid})
  streamed = await asyncio.wait_for(first, 15)

mine = await new_fills(client, known[0], count=2)
theirs = await new_fills(counterparty, known[1], count=2)
after = (await balances(client), await balances(counterparty))
{
  'streamed': (streamed.qty, streamed.price, streamed.fee),
  'account': {
    'fills': [(f.qty, f.price, f.maker, f.fee) for f in mine],
    'expected': expected(before[0], mine),
    'actual': after[0],
  },
  'counterparty': {
    'fills': [(f.qty, f.price, f.maker, f.fee) for f in theirs],
    'expected': expected(before[1], theirs),
    'actual': after[1],
  },
}

# %%
# Classic-mode collateral: the counterparty switches to classic, moves 100 USDC to its spot
# side, rests a 12 USDC bid, tries an 89 USDC bid (above the 88 free), and switches back.
await counterparty.tx.cancel_all_orders({'mode': 'immediate'})
await asyncio.sleep(2)
await counterparty.tx.update_account_config('classic')
await asyncio.sleep(3)
await counterparty.tx.transfer(
  to_account_index=SUB, amount=100 * 10**6, from_route='perps', to_route='spot'
)
await asyncio.sleep(3)
await create(
  counterparty, ETH_USDC, {'type': 'POST_ONLY', 'qty': Decimal('0.0120'), 'price': low}
)
await asyncio.sleep(3)
classic = await account(counterparty)
try:
  await create(
    counterparty,
    ETH_USDC,
    {'type': 'POST_ONLY', 'qty': Decimal('0.0890'), 'price': low},
  )
  above_free = 'accepted'
except Exception as e:
  above_free = f'rejected: {e}'
await counterparty.tx.cancel_all_orders({'mode': 'immediate'})
await asyncio.sleep(2)
await counterparty.tx.update_account_config('unified')
await asyncio.sleep(3)
unified = await account(counterparty)
{
  'classic': (classic['account_trading_mode'], collateral_of(classic, 3)),
  'classic 89 USDC bid (free is 88)': above_free,
  'unified again': (unified['account_trading_mode'], collateral_of(unified, 3)),
}

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | Numeric market ids from `orderBookDetails(filter='spot')`. |
# | `depth` | verified | As perp; testnet spot books are thin. |
# | `depth_stream` | verified | As perp. |
# | `tickers` | verified | `spot_market_stats:all`; no best-level sizes. |
# | `rules` | verified | As perp, with `fee_asset=None`: fees are charged in the received asset, per ADR 0028. |
# | `fees` | verified | Account fee ticks, as perp; spot fills carry the same ticks. |
# | `candles` | verified | 15m/1h/4h over two days, exact counts; zero volumes map to 0. |
# | `query_order` | verified | Live orders queried until indexed; cancelled status seen. |
# | `open_orders` | verified | Live orders in the trading cells. |
# | `trades_history` | verified | Fee in the received asset (base on buys, quote on sells) at the role's tick; expected balances equal actual for both accounts and all four role/side combinations. |
# | `trades_stream` | verified | `account_market` serves spot; a live sell was streamed with its USDC fee. |
# | `position` | verified | Base asset balance. |
# | `collateral` | verified | Classic: `balance`, free `balance - locked` (an 89 USDC bid over 88 free was rejected). Unified: USDC `margin_balance`, free `available_balance - locked` (bounds measured with orders accepted/rejected either side). |
# | `available_notional` | verified | Free quote collateral. |
# | `place_order` | verified | LIMIT, POST_ONLY and MARKET placed live (the venue's market order works on spot). |
# | `cancel_order` | verified | By client index. |
# | `cancel_orders` | verified | One cancel per order. |
# | `cancel_open_orders` | verified | Each open order cancelled: the venue's market-scoped cancel-all rejects spot markets (`21619`); LIT/USDC orders survived. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them. These are testnet ids; only mainnet instruments are catalogued.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(spot_markets=set(listed), assets=set(assets))
gap('lighter', ids, load_catalogue())

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
