# %% [markdown]
# # extended `market` PoC
#
# Maps `typed_extended` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Public market data runs against **mainnet**, credential-free in substance (the mainnet client carries a read-only API key, which public endpoints ignore). Account reads run against two accounts:
#
# - mainnet account 321158 (`EXTENDED_API_KEY`, read-only, no funds): every account read, which comes back empty;
# - testnet account 3880 (`EXTENDED_TESTNET_*`, signing, ~1000 test USD): the same reads where the empty account cannot show a shape (fills, a closed order, a funded balance), and the trading cells, which are written but never run.
#
# IDs are the venue's names: markets are `name` (`BTC-USD`), the one collateral and fee asset is `USD`. Perpetuals are `type: PERPETUAL`; the three spot markets (`BTCSPOT-USD`, ...) belong to a spot surface. Testnet market names match mainnet's; only mainnet instruments are catalogued.

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

from dotenv import load_dotenv
from typed_extended import Extended
from typed_extended.account.balance import Balance
from typed_extended.account.schemas import Order as ExtendedOrder
from typed_extended.account.trades import AccountTrade
from typed_extended.info.candles import Candle as ExtendedCandle
from typed_extended.info.markets import Market as ExtendedMarket
from typed_extended.info.schemas import OrderbookLevel
from typed_extended.orders.create import LimitOrderRequest, MarketOrderRequest
from typed_extended.orders.create_rfq import RfqLimitOrderRequest, RfqMarketOrderRequest
from typed_extended.streams.account import StreamTrade
from typed_extended.streams.schemas import StreamOrderbookLevel

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
from tribulnation.sdk.market.types.candles import EPOCH, candle_width

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(Extended.new(network='mainnet'))
"""Mainnet, read-only: market data, and the empty account's reads."""
testnet = await stack.enter_async_context(Extended.new(network='testnet'))
"""Testnet, signing: the funded account's reads, and the (never run) trading cells."""

MARKETS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
ETH = 'ETH-USD'
RFQ = 'OP-USD'
"""An RFQ market: its real book is quotes, published on a dedicated stream only."""
USD = 'USD'
"""The collateral asset: margin, PnL, trading fees and funding all settle in it."""
FUNDING_INTERVAL = timedelta(hours=1)
"""Extended applies funding once an hour (the rate is re-estimated every minute)."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)
history_start = end - timedelta(days=30)


async def market_table(on: Extended = client) -> dict[str, ExtendedMarket]:
  """Every market of the deployment (perpetual and spot, delisted included), by name."""
  return {m['name']: m for m in await on.info.markets()}


def listed_perps(table: Mapping[str, ExtendedMarket]) -> list[str]:
  """The perpetuals that are not delisted (`ACTIVE`, `REDUCE_ONLY`, `PRELISTED`)."""
  return [
    name
    for name, m in table.items()
    if m['type'] == 'PERPETUAL' and m['status'] != 'DELISTED'
  ]


async def balance(on: Extended = client) -> Balance | None:
  """The account's balance; `None` for a sub-account holding nothing.

  The docs: "Returns a 404 error if the user's balance is 0", which the client reads as
  `None`. The account stream's `BALANCE` snapshot of the same account carries every
  figure as `0` (cell below).
  """
  return await on.account.balance()


async def account_leverage(market_id: str, on: Extended = client) -> Decimal:
  """The account's leverage setting on the market (the venue default, 10, until changed)."""
  rows = await on.account.leverage([market_id])
  return rows[0]['leverage']


details = await market_table()
{
  'typed-extended': version('typed-extended'),
  'markets': len(details),
  'listed perps': len(listed_perps(details)),
  'rfq perps': sum(1 for n in listed_perps(details) if details[n]['isRfq']),
  'testnet markets': len(await market_table(testnet)),
}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_extended',
    'Extended',
    grep=r'^info\.(markets|orderbook|market_stats|candles|funding_rates)|^account\.(balance|fees|leverage|positions|open_orders|order|trades|funding_history)|^orders\.(create|cancel|mass_cancel)|^streams\.(orderbooks|rfq_orderbooks|account)',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.
#
# Every perpetual that is not `DELISTED`, from `info.markets`: `ACTIVE`, `REDUCE_ONLY` and `PRELISTED` ones (`rules().api` says which trade). Delisted markets are left out: an inactive one (`active: false`) has no order book at all (`info.orderbook` returns `None`) and an index price of `0`. Their fills still show up in exchange-wide history, which never consults this list.


# %%
async def markets(*, on: Extended = client) -> Sequence[str]:
  """Every listed perpetual, by name."""
  return listed_perps(await market_table(on))


listed = await markets()
assert set(MARKETS) | {RFQ} <= set(listed)
{
  'count': len(listed),
  'statuses': sorted({details[m]['status'] for m in listed}),
  'sample': listed[:8],
  'testnet': len(await markets(on=testnet)),
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.
#
# Order-book markets: `info.orderbook`, the whole aggregated book (thousands of levels on BTC), with no timestamp, so `time` is `None`; an inactive or unknown market has no book (`None`), which raises. RFQ markets: the REST book is the venue's *indicative* book (empty on `OP-USD`); the real book is the quotes, which the venue publishes only on the `orderbooks/rfq` stream, so `depth` takes that stream's first snapshot, stamped with its `ts`.


# %%
def book_entries(rows: Sequence[OrderbookLevel]) -> list[Book.Entry]:
  """Book entries from REST price levels."""
  return [Book.Entry(r['price'], r['qty']) for r in rows]


def snapshot_entries(rows: Sequence[StreamOrderbookLevel]) -> list[Book.Entry]:
  """Book entries from a stream snapshot, whose `q` is the absolute size."""
  return [Book.Entry(r['p'], r['q']) for r in rows]


async def rfq_book(market_id: str, on: Extended) -> Book:
  """The first snapshot of an RFQ market's quotes stream."""
  async with on.streams.rfq_orderbooks(market_id) as stream:
    async for frame in stream:
      if frame['type'] == 'SNAPSHOT':
        return Book(
          bids=snapshot_entries(frame['data']['b']),
          asks=snapshot_entries(frame['data']['a']),
          time=frame['ts'],
        )
  raise RuntimeError(f'{market_id} quotes stream closed before its snapshot')


async def depth(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  settings: Settings = {},
  on: Extended = client,
) -> Book:
  """The REST book, or the RFQ quotes snapshot on an RFQ market."""
  if details[market_id]['isRfq']:
    book = await rfq_book(market_id, on)
  else:
    raw = await on.info.orderbook(market_id)
    if raw is None:
      raise RuntimeError(f'{market_id} has no order book: inactive or unknown')
    book = Book(bids=book_entries(raw['bid']), asks=book_entries(raw['ask']))
  return book.limit(levels) if levels is not None else book


books = {m: await depth(m) for m in [*MARKETS, RFQ]}
{
  m: (len(b.bids), len(b.asks), b.best_bid.price, b.best_ask.price, b.time)
  for m, b in books.items()
}


# %%
# REST against the stream's snapshot (the same full book), the `depth='1'` best-level
# feed, the indicative REST book of an RFQ market against its quotes, and the missing
# book of an inactive delisted market and of an unknown one.
async def stream_snapshot(market_id: str, *, bbo: bool = False) -> tuple[int, int]:
  """Level counts of the first `orderbooks` frame."""
  manager = (
    client.streams.orderbooks(market_id, depth='1')
    if bbo
    else client.streams.orderbooks(market_id)
  )
  async with manager as stream:
    async for frame in stream:
      return len(frame['data']['b']), len(frame['data']['a'])
  raise RuntimeError('orderbooks stream closed before its snapshot')


indicative = await client.info.orderbook(RFQ)
assert indicative is not None
{
  'BTC rest': (len(books['BTC-USD'].bids), len(books['BTC-USD'].asks)),
  'BTC stream snapshot': await stream_snapshot('BTC-USD'),
  'BTC depth=1': await stream_snapshot('BTC-USD', bbo=True),
  'RFQ rest (indicative)': (len(indicative['bid']), len(indicative['ask'])),
  'RFQ quotes': (len(books[RFQ].bids), len(books[RFQ].asks)),
  'inactive MATIC-USD': await client.info.orderbook('MATIC-USD'),
  'unknown NOPE-USD': await client.info.orderbook('NOPE-USD'),
}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.
#
# `orderbooks/{market}` (`orderbooks/rfq/{market}` on an RFQ market) sends a snapshot, then deltas every 100 ms, and a fresh snapshot every minute, which replaces the local book. In a delta `q` is the change and `c` the absolute size (`0` deletes the level). `seq` counts frames per connection from 1; a gap fails the stream. `time` is the frame's `ts`.


# %%
def delta_entries(rows: Sequence[StreamOrderbookLevel]) -> list[Book.Entry]:
  """Book entries from a delta, at their absolute size `c`."""
  entries: list[Book.Entry] = []
  for r in rows:
    size = r.get('c')
    if size is None:
      raise RuntimeError(f'delta level without its absolute size: {r}')
    entries.append(Book.Entry(r['p'], size))
  return entries


@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
  settings: Settings = {},
  on: Extended = client,
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Maintain a local book from snapshots and deltas."""
  manager = (
    on.streams.rfq_orderbooks(market_id)
    if details[market_id]['isRfq']
    else on.streams.orderbooks(market_id)
  )
  async with manager as stream:

    async def books():
      book = Book()
      seq: int | None = None
      async for frame in stream:
        if seq is not None and frame['seq'] != seq + 1:
          raise RuntimeError(f'orderbook gap: {seq} -> {frame["seq"]}')
        seq = frame['seq']
        data = frame['data']
        if frame['type'] == 'SNAPSHOT':
          book = Book(
            bids=snapshot_entries(data['b']),
            asks=snapshot_entries(data['a']),
            time=frame['ts'],
          )
        else:
          book.update(
            Book(
              bids=delta_entries(data['b']),
              asks=delta_entries(data['a']),
              time=frame['ts'],
            )
          )
        yield book.limit(levels) if levels is not None else book.copy()

    yield books()


seen: dict[str, list[tuple[int, int, Decimal, Decimal, datetime | None]]] = {}
for m in ('BTC-USD', RFQ):
  seen[m] = []
  async with depth_stream(m, levels=10) as stream:
    async for update in stream:
      seen[m].append(
        (
          len(update.bids),
          len(update.asks),
          update.best_bid.price,
          update.best_ask.price,
          update.time,
        )
      )
      if len(seen[m]) == (5 if m == 'BTC-USD' else 2):
        break
seen


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.
#
# One `info.markets` read carries every market's `marketStats`: last price, best bid and ask, and 24h volume in the base asset (`dailyVolumeBase`) and in the collateral asset (`dailyVolume`, USD, the quote). There is no size at the best levels, so `bid_qty`/`ask_qty` stay `None`. A price of `0` is the venue's "none" (a reduce-only market with an empty book reads `0` bid and ask) and maps to `None`. On RFQ markets bid and ask are the indicative book's.


# %%
def price_or_none(value: Decimal) -> Decimal | None:
  """A `marketStats` price, or `None` where the venue sends `0` (no such price)."""
  return value if value != 0 else None


async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Tickers from the `info.markets` statistics."""
  table = await market_table()
  perps = listed_perps(table)
  wanted = perps if markets is None else [m for m in markets if m in perps]
  return {
    m: Ticker(
      last=price_or_none(table[m]['marketStats']['lastPrice']),
      bid=price_or_none(table[m]['marketStats']['bidPrice']),
      ask=price_or_none(table[m]['marketStats']['askPrice']),
      base_volume_24h=table[m]['marketStats']['dailyVolumeBase'],
      quote_volume_24h=table[m]['marketStats']['dailyVolume'],
    )
    for m in wanted
  }


all_tickers = await tickers()
{
  'all': len(all_tickers),
  'selected': await tickers([*MARKETS, RFQ]),
  'reduce-only MKR': all_tickers.get('MKR-USD'),
  'empty': await tickers([]),
}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.
#
# From `tradingConfig`: tick `minPriceChange`, step `minOrderSizeChange`, minimum size `minOrderSize`. The limit-price band is side-specific, as on Bitget: a buy may not exceed mark x (1 + `limitPriceCap`) and a sell may not go below mark x (1 - `limitPriceFloor`) (Trading Rules docs). The order-value and position-value caps are notionals with no `Rules` field and stay in `details`. `fees` is `None`: no endpoint publishes a standard schedule (the account endpoint differs by market group, 0/2.5 bps or 0/1 bp on the mainnet account), and rules never read the account. `api` is `status == 'ACTIVE'`.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Precision, size floor, price band and caps from `tradingConfig`."""
  m = (await client.info.markets([market_id]))[0]
  config = m['tradingConfig']
  return Rules(
    fee_asset=m['collateralAssetName'],
    tick_size=config['minPriceChange'],
    step_size=config['minOrderSizeChange'],
    fixed_min_qty=config['minOrderSize'],
    rel_min_price=1 - config['limitPriceFloor'],
    rel_max_price=1 + config['limitPriceCap'],
    fees=None,
    api=m['status'] == 'ACTIVE',
    details={
      'status': m['status'],
      'is_rfq': m['isRfq'],
      'trading_hours': m.get('tradingHours'),
      'max_market_order_value': config['maxMarketOrderValue'],
      'max_limit_order_value': config['maxLimitOrderValue'],
      'max_position_value': config['maxPositionValue'],
      'max_leverage': config['maxLeverage'],
      'max_num_orders': config['maxNumOrders'],
    },
  )


{m: await rules(m) for m in [*MARKETS, RFQ, 'MKR-USD']}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.
#
# `account.fees` returns the account's maker and taker rates per market, as fractions; the same rate applies to buys and sells. `builderFeeRate` is `0` without a builder and is not part of the account's rate. The docs add that on RFQ markets the account's own orders always pay the taker rate, even resting (see the design questions).


# %%
async def fees(
  market_id: str, /, *, refetch: bool = False, on: Extended = client
) -> Fees:
  """The account's maker/taker rates on the market."""
  row = (await on.account.fees([market_id]))[0]
  return Fees.symmetric(maker=row['makerFeeRate'], taker=row['takerFeeRate'])


{
  'mainnet': {m: await fees(m) for m in [*MARKETS, RFQ]},
  'testnet': {m: await fees(m, on=testnet) for m in MARKETS},
}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.
#
# `info.candles_paged` with `candleType='trades'`, newest first, stamped with the open time; `endTime` is exclusive. A request covers the `limit` intervals before `endTime` (at most 2800), and the client's walk moves `endTime` back to each page's oldest open. The walk starts at `end` with `limit` the number of grid opens in `[start, end)`, at most 1000, and stops once a page reaches `start`; older rows are dropped. Volume is `v` (base); there is no quote volume or trade count. Daily candles are `P1D`, aligned to UTC midnight.

# %%
INTERVALS: dict[
  CandleInterval, Literal['PT1M', 'PT5M', 'PT15M', 'PT1H', 'PT4H', 'P1D']
] = {
  '1m': 'PT1M',
  '5m': 'PT5M',
  '15m': 'PT15M',
  '1h': 'PT1H',
  '4h': 'PT4H',
  '1d': 'P1D',
}
CANDLES_PAGE = 1000


def parse_candle(c: ExtendedCandle) -> Candle:
  """An SDK candle from a venue trade candle."""
  return Candle(
    time=c['T'], open=c['o'], high=c['h'], low=c['l'], close=c['c'], volume=c.get('v')
  )


async def candles(
  market_id: str,
  /,
  interval: CandleInterval,
  start: datetime,
  end: datetime,
  *,
  on: Extended = client,
):
  """Candles opening in `[start, end)`, newest first, walked back from `end`."""
  width = candle_width(interval)
  offset = (start - EPOCH) % width
  first = start if not offset else start - offset + width
  count = -((first - end) // width)
  if count <= 0:
    return
  pages = on.info.candles_paged(
    market_id,
    candle_type='trades',
    interval=INTERVALS[interval],
    limit=min(count, CANDLES_PAGE),
    end_time=end,
  )
  async for page in pages:
    rows = [parse_candle(c) for c in page if c['T'] >= start]
    if rows:
      yield rows
    if not page or min(c['T'] for c in page) <= first:
      return


candle_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
candle_probe = {}
for interval in INTERVALS:
  window_start = candle_end - candle_width(interval) * 5
  rows = [
    c async for page in candles(ETH, interval, window_start, candle_end) for c in page
  ]
  candle_probe[interval] = (len(rows), rows[0] if rows else None)
candle_probe

# %%
# Cross-page: 2500 one-minute candles (three pages), without duplicates or gaps, and an
# unaligned start; then the per-request cap the page size stays under.
cross_start = candle_end - timedelta(minutes=2500)
pages = [page async for page in candles('BTC-USD', '1m', cross_start, candle_end)]
times = sorted(c.time for page in pages for c in page)
unaligned = [
  c
  async for p in candles(
    'BTC-USD', '5m', candle_end - timedelta(minutes=5 * 1200 + 3), candle_end
  )
  for c in p
]
capped = await client.info.candles(
  'BTC-USD', candle_type='trades', interval='PT1M', limit=10000
)
{
  'pages': [len(p) for p in pages],
  'unique': len(set(times)) == len(times),
  'missing_minutes': 2500 - len(times),
  'first': times[0],
  'last': times[-1],
  'unaligned 5m x1200': len(unaligned),
  'limit=10000 returns': len(capped),
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.
#
# The SDK order id is Extended's order `id` (a 64-bit integer, as a string): `place_order` gets it back on acceptance and cancels take it. `account.order` looks it up, open or closed; an unknown id is `None` (the venue's bodiless `404`). Prices and sizes are unsigned with `side` beside them. On mainnet an unknown id; on testnet a closed order of the account.

# %%
ACTIVE_STATUSES = {'NEW', 'PARTIALLY_FILLED', 'UNTRIGGERED'}


def parse_order(o: ExtendedOrder) -> OrderState:
  """An SDK order state from a venue order; sells are negative."""
  price = o.get('price')
  if price is None:
    raise ValueError(f'order {o["id"]} ({o["type"]}) has no price')
  sign = -1 if o['side'] == 'SELL' else 1
  return OrderState(
    id=str(o['id']),
    price=price,
    qty=o['qty'] * sign,
    filled_qty=(o.get('filledQty') or Decimal(0)) * sign,
    active=o['status'] in ACTIVE_STATUSES,
    details=o,
  )


async def query_order(
  market_id: str, /, id: str, *, on: Extended = client
) -> OrderState | None:
  """Look the order up by its Extended id."""
  o = await on.account.order(int(id))
  return parse_order(o) if o is not None and o['market'] == market_id else None


closed = (await testnet.account.orders_history(limit=1))['data'][0]
closed_state = await query_order(closed['market'], str(closed['id']), on=testnet)
{
  'mainnet unknown id': await query_order(ETH, '123456789'),
  'testnet closed': (
    closed_state.id,
    closed_state.price,
    closed_state.qty,
    closed_state.filled_qty,
    closed_state.active,
    closed['status'],
    closed['type'],
  )
  if closed_state
  else None,
}


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.
#
# `account.open_orders` filtered by market and to `type='LIMIT'`, the only kind `place_order` leaves resting (market orders are IOC). Conditional, TP/SL and TWAP orders are left out: a TP/SL order has no price (see the design questions). Empty on both accounts: a resting limit order would populate it.


# %%
async def open_orders(
  market_id: str, /, *, on: Extended = client
) -> Sequence[OrderState]:
  """The market's open limit orders."""
  rows = await on.account.open_orders([market_id], type='LIMIT')
  return [parse_order(o) for o in rows]


{
  'mainnet': {m: await open_orders(m) for m in MARKETS},
  'testnet': {m: await open_orders(m, on=testnet) for m in MARKETS},
}


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one market or the whole exchange.
#
# `account.trades`, newest first, spot and perpetual fills together, at most 10,000 records in all, with no time filter: pages are read until a fill precedes `start`. The exchange-wide form drops spot fills by the market's `type`, read from `info.markets` (delisted markets stay listed there). `qty` is unsigned with `side`; `fee` is in the collateral asset (USD), paid-positive; `isTaker` gives the role. `order_id` is the Extended order id, `client_order_id` the order's `externalOrderId`. Empty on mainnet; testnet holds four ETH fills.

# %%
TRADES_PAGE = 100


def parse_trade(t: AccountTrade | StreamTrade) -> Trade:
  """The account's fill, with its USD fee."""
  return Trade(
    id=str(t['id']),
    order_id=str(t['orderId']),
    client_order_id=t.get('externalOrderId'),
    price=t['price'],
    qty=-t['qty'] if t['side'] == 'SELL' else t['qty'],
    time=t['createdTime'],
    maker=not t['isTaker'],
    fee=Trade.Fee(amount=t['fee'], asset=USD),
    details=t,
  )


async def trades_history(
  market_id: str | None,
  /,
  start: datetime,
  end: datetime,
  *,
  on: Extended = client,
) -> AsyncIterable[Sequence[Trade]]:
  """Personal perpetual fills with `start <= time <= end`, newest first."""
  table = await market_table(on)
  pages = on.account.trades_paged(
    None if market_id is None else [market_id], limit=TRADES_PAGE
  )
  async for page in pages:
    rows: list[Trade] = []
    for t in page:
      if t['createdTime'] > end:
        continue
      if t['createdTime'] < start:
        if rows:
          yield rows
        return
      perp = t['market'] in table and table[t['market']]['type'] == 'PERPETUAL'
      if market_id is not None:
        rows.append(parse_trade(t))
      elif perp:
        rows.append(ExchangeTrade(**vars(parse_trade(t)), market_id=t['market']))
    if rows:
      yield rows


def collect(pages: list[Sequence[Trade]]) -> list[Trade]:
  """Flatten pages."""
  return [t for page in pages for t in page]


by_market = {
  m: collect([p async for p in trades_history(m, history_start, end, on=testnet)])
  for m in MARKETS
}
exchange_wide = collect(
  [p async for p in trades_history(None, history_start, end, on=testnet)]
)
testnet_fees = {m: await fees(m, on=testnet) for m in MARKETS}
{
  'mainnet': collect([p async for p in trades_history(None, history_start, end)]),
  'testnet per market': {
    m: [
      (
        t.qty,
        t.price,
        'maker' if t.maker else 'taker',
        t.fee.amount if t.fee else None,
        t.details['value']
        * (testnet_fees[m].maker_buy if t.maker else testnet_fees[m].taker_buy),
        t.order_id,
        t.client_order_id,
      )
      for t in ts
    ]
    for m, ts in by_market.items()
  },
  'testnet exchange-wide': (
    len(exchange_wide),
    exchange_wide[0] if exchange_wide else None,
  ),
  'exchange_equals_union': sorted(t.id or '' for t in exchange_wide)
  == sorted(t.id or '' for ts in by_market.values() for t in ts),
}


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.
#
# The private `account` stream sends snapshots of open orders, positions, spot balances and the balance, then every change; fills arrive as `TRADE` frames, rows shaped like `account.trades`. Filtered to the market. Run on mainnet (the testnet stream host answered `503` on every stream, public ones included): the snapshots arrive, no fill does, so `empty`; a fill on the account while subscribed would populate it.


# %%
@asynccontextmanager
async def trades_stream(
  market_id: str,
  /,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
  settings: Settings = {},
  on: Extended = client,
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """The account's new fills on one market."""
  async with on.streams.account() as stream:

    async def trades():
      async for frame in stream:
        data = frame.get('data')
        if frame['type'] != 'TRADE' or data is None:
          continue
        for t in data.get('trades', []):
          if t['market'] == market_id:
            yield parse_trade(t)

    yield trades()


snapshot_types: list[str] = []
async with client.streams.account() as account_stream:
  async for frame in account_stream:
    snapshot_types.append(frame['type'])
    if len(snapshot_types) == 4:
      break


async def first_fill(market_id: str, seconds: float) -> Trade | None:
  """The first streamed fill within `seconds`, if any."""
  async with trades_stream(market_id) as stream:
    try:
      return await asyncio.wait_for(anext(aiter(stream)), seconds)
    except TimeoutError:
      return None


{'snapshots': snapshot_types, 'fill within 10 s': await first_fill(ETH, 10)}


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def position(market_id: str, /, *, on: Extended = client) -> Position:
  """Defers to `perp_position`."""
  return await perp_position(market_id, on=on)


# %% [markdown]
# ## `available_notional`
#
# Fetch the maximum notional position you can open right now.
#
# The SDK default: free collateral (`availableForTrade`, see `perp_collateral`) times the account's leverage on the market. The margin schedule also caps the position value per leverage (`|position + new order + triggered orders| <= max position value for the leverage`, Margin Schedule docs); applying it as an ADR 0041 cap is a design question. Mainnet: `0` (no funds); testnet: the funded figure.


# %%
async def available_notional(market_id: str, /, *, on: Extended = client) -> Decimal:
  """Free collateral times the account's leverage on the market."""
  b, leverage = await asyncio.gather(balance(on), account_leverage(market_id, on))
  free = b['availableForTrade'] if b is not None else Decimal(0)
  return free * leverage


{
  'mainnet': {m: await available_notional(m) for m in MARKETS},
  'testnet': {m: await available_notional(m, on=testnet) for m in MARKETS},
}


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.
#
# `orders.create` (order-book markets) or `orders.create_rfq` (RFQ markets: post-only is refused there, so `POST_ONLY` raises before signing). The core signs the order with the Stark key and fills the fee cap (the account's maker rate for post-only, taker otherwise), the nonce and, when absent, the client id (the order hash) and the expiry (one hour). Mapping: `LIMIT` is `GTT`, `POST_ONLY` is `GTT` with `postOnly`, `MARKET` is the venue's `MARKET` (`IOC`) bounded by `price`. Resting orders get an explicit expiry, the testnet's 28-day maximum (mainnet allows 90 days), rather than the core's one hour. `client_order_id` is sent as `id` (the venue's `externalId`). Self-trade protection is `ACCOUNT`. Acceptance is asynchronous: the response carries the order id, and a later rejection arrives on the account stream as `REJECTED`, so `filled_qty` stays `None`.

# %%
# not executed: state-changing; verified on testnet in qualification
trader = testnet
ORDER_LIFETIME = timedelta(days=28)
"""Resting-order lifetime: testnet's maximum expiry (90 days on mainnet)."""


async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Sign and send one order."""
  qty = Decimal(order['qty'])
  price = Decimal(order['price'])
  side: Literal['BUY', 'SELL'] = 'BUY' if qty > 0 else 'SELL'
  rfq = details[market_id]['isRfq']
  client_id = order.get('client_order_id')
  if order['type'] == 'MARKET':
    market: MarketOrderRequest = {
      'type': 'MARKET',
      'market': market_id,
      'side': side,
      'qty': abs(qty),
      'price': price,
      'timeInForce': 'IOC',
      'selfTradeProtectionLevel': 'ACCOUNT',
    }
    if client_id is not None:
      market['id'] = client_id
    if rfq:
      rfq_market: RfqMarketOrderRequest = {**market}
      placed = await trader.orders.create_rfq(rfq_market)
    else:
      placed = await trader.orders.create(market)
  elif rfq:
    if order['type'] == 'POST_ONLY':
      raise ValueError(f'{market_id} is an RFQ market: post-only orders are refused')
    rfq_limit: RfqLimitOrderRequest = {
      'type': 'LIMIT',
      'market': market_id,
      'side': side,
      'qty': abs(qty),
      'price': price,
      'timeInForce': 'GTT',
      'selfTradeProtectionLevel': 'ACCOUNT',
      'expiryEpochMillis': datetime.now(timezone.utc) + ORDER_LIFETIME,
    }
    if client_id is not None:
      rfq_limit['id'] = client_id
    placed = await trader.orders.create_rfq(rfq_limit)
  else:
    limit: LimitOrderRequest = {
      'type': 'LIMIT',
      'market': market_id,
      'side': side,
      'qty': abs(qty),
      'price': price,
      'timeInForce': 'GTT',
      'selfTradeProtectionLevel': 'ACCOUNT',
      'expiryEpochMillis': datetime.now(timezone.utc) + ORDER_LIFETIME,
      'postOnly': order['type'] == 'POST_ONLY',
    }
    if client_id is not None:
      limit['id'] = client_id
    placed = await trader.orders.create(limit)
  return OrderResponse(id=str(placed['id']), details=placed)


# A resting POST_ONLY buy 10% below the best bid, then its state.
bid = (await depth(ETH, levels=1, on=trader)).best_bid.price
tick = (await rules(ETH)).tick_size
resting = await place_order(
  ETH,
  {
    'type': 'POST_ONLY',
    'qty': Decimal('0.01'),
    'price': (bid * Decimal('0.9')).quantize(tick),
  },
)
await asyncio.sleep(2)
{
  'placed': resting,
  'query': await query_order(ETH, resting.id, on=trader),
  'open': [o.id for o in await open_orders(ETH, on=trader)],
}


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.
#
# `orders.cancel` by Extended id. Cancellation is asynchronous: the call only acknowledges the request.


# %%
# not executed: state-changing; verified on testnet in qualification
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Cancel by Extended id."""
  return await trader.orders.cancel(int(id))


await cancel_order(ETH, resting.id)
await asyncio.sleep(2)
await query_order(ETH, resting.id, on=trader)


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.
#
# One `orders.mass_cancel` request with the Extended ids.


# %%
# not executed: state-changing; verified on testnet in qualification
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Mass-cancel by Extended ids."""
  return await trader.orders.mass_cancel([int(id) for id in ids])


low = (bid * Decimal('0.8')).quantize(tick)
pair = [
  await place_order(ETH, {'type': 'LIMIT', 'qty': Decimal('0.01'), 'price': low})
  for _ in range(2)
]
await asyncio.sleep(2)
await cancel_orders(ETH, [p.id for p in pair])
await asyncio.sleep(2)
[o.id for o in await open_orders(ETH, on=trader)]


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.
#
# `orders.mass_cancel(markets=[market])`, the venue's cancel-all scoped to the market. It also cancels conditional and TP/SL orders, which `open_orders` leaves out (see the design questions).


# %%
# not executed: state-changing; verified on testnet in qualification
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """The venue's cancel-all, scoped to one market."""
  return await trader.orders.mass_cancel(markets=[market_id])


eth_orders = [
  await place_order(ETH, {'type': 'LIMIT', 'qty': Decimal('0.01'), 'price': low})
  for _ in range(2)
]
await asyncio.sleep(2)
await cancel_open_orders(ETH)
await asyncio.sleep(2)
[o.id for o in await open_orders(ETH, on=trader)]


# %% [markdown]
# ## `index`
#
# Fetch the market index price.
#
# `marketStats.indexPrice` of `info.markets([market])`, which refuses an unknown market (`1001`); `info.market_stats` answers all zeros for one instead.


# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  """The market's index price."""
  m = (await client.info.markets([market_id]))[0]
  return m['marketStats']['indexPrice']


{m: await index(m) for m in [*MARKETS, RFQ]}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.
#
# `marketStats.fundingRate` is the venue's current one-minute estimate of the hourly rate, as a fraction (BTC's `0.000013` is the documented interest component, 0.01% per 8 hours, plus premium); positive means longs pay. `nextFundingRate` is, despite its name, the next payment time. The venue reports no premium.


# %%
async def next_funding(market_id: str, /) -> NextFunding:
  """The estimated rate of the next hourly payment."""
  stats = (await client.info.markets([market_id]))[0]['marketStats']
  return NextFunding(
    rate=stats['fundingRate'],
    time=stats['nextFundingRate'],
    interval=FUNDING_INTERVAL,
  )


{m: await next_funding(m) for m in MARKETS}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.
#
# One `info.markets` read: index, mark, the funding estimate and its time, and open interest in base units (`openInterestBase`).


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Index, mark, funding estimate and base-unit open interest."""
  table = await market_table()
  perps = listed_perps(table)
  wanted = perps if markets is None else [m for m in markets if m in perps]
  return {
    m: PerpStats(
      index=table[m]['marketStats']['indexPrice'],
      mark=table[m]['marketStats']['markPrice'],
      funding=table[m]['marketStats']['fundingRate'],
      next_funding_time=table[m]['marketStats']['nextFundingRate'],
      funding_interval=FUNDING_INTERVAL,
      open_interest=table[m]['marketStats']['openInterestBase'],
    )
    for m in wanted
  }


all_stats = await perp_stats()
{
  'all': len(all_stats),
  'zero index': [m for m, s in all_stats.items() if s.index == 0],
  'selected': await perp_stats(MARKETS),
  'empty': await perp_stats([]),
}


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.
#
# `info.funding_rates_paged`: the applied hourly rates, newest first, as fractions (positive: longs pay shorts, Funding Payments docs). Both bounds are inclusive to the millisecond (stamps carry ~1 s of jitter past the hour). A request returns at most 1000 rows (the documented `limit` and `cursor` are ignored live), and the client's walk moves `endTime` to the oldest row of each full page until it reaches `start`. `start=None` starts at the market's `createdAt`.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Applied hourly rates with `start <= time <= end`, newest first."""
  lower = start or details[market_id].get('createdAt') or EPOCH
  upper = end or datetime.now(timezone.utc)
  pages = client.info.funding_rates_paged(market_id, start_time=lower, end_time=upper)
  async for page in pages:
    if page:
      yield [FundingRate(rate=r['f'], time=r['T']) for r in page]


rates = {
  m: [r async for page in funding_rates(m, end - timedelta(days=2), end) for r in page]
  for m in MARKETS
}
bounded_lower = rates[ETH][5].time
bounded = [
  r
  async for page in funding_rates(ETH, bounded_lower, rates[ETH][3].time)
  for r in page
]
full = [page async for page in funding_rates('BTC-USD')]
{
  'counts': {m: len(rs) for m, rs in rates.items()},
  'latest': {m: rs[0] for m, rs in rates.items()},
  'inclusive_bounds': [r.time for r in bounded],
  'all_history_pages': [len(p) for p in full],
  'all_history_unique': len({r.time for p in full for r in p})
  == sum(len(p) for p in full),
  'negative rates (BTC)': sum(1 for p in full for r in p if r.rate < 0),
}


# %% [markdown]
# ## `funding_payments`
#
# Fetch personal funding payments for one market or the whole exchange.
#
# `account.funding_history` from `start` (its only time filter; pages follow its cursor), with `paidTime > end` dropped locally; the exchange-wide form omits `market`, and only perpetuals pay funding. The amount is `fundingFee`. The docs give the payment as `size x mark x (-rate)` and the portfolio endpoint's twin field as "negative when paid", so it reads as received-positive, as ADR 0035 wants; no payment has been observed to confirm it. Empty on both accounts: a position held across an hourly settlement would populate it.

# %%
FUNDING_PAGE = 100


async def funding_payments(
  market_id: str | None,
  /,
  start: datetime,
  end: datetime,
  *,
  on: Extended = client,
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal funding payments with `start <= time <= end`."""
  pages = on.account.funding_history_paged(
    None if market_id is None else [market_id], start_time=start, limit=FUNDING_PAGE
  )
  async for page in pages:
    rows: list[FundingPayment] = []
    for f in page:
      if not start <= f['paidTime'] <= end:
        continue
      rows.append(
        FundingPayment(amount=f['fundingFee'], time=f['paidTime'])
        if market_id is not None
        else ExchangeFundingPayment(
          amount=f['fundingFee'], time=f['paidTime'], market_id=f['market']
        )
      )
    if rows:
      yield rows


{
  name: {
    'per market': {
      m: [
        p async for page in funding_payments(m, history_start, end, on=on) for p in page
      ]
      for m in MARKETS
    },
    'exchange-wide': [
      p
      async for page in funding_payments(None, history_start, end, on=on)
      for p in page
    ],
  }
  for name, on in (('mainnet', client), ('testnet', testnet))
}


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.
#
# `account.positions` for the market: `size` is absolute with `side` (`LONG`/`SHORT`), `openPrice` the entry. No row means flat. Empty on both accounts: an open position would populate it.


# %%
async def perp_position(market_id: str, /, *, on: Extended = client) -> PerpPosition:
  """The account's signed position and entry price."""
  for p in await on.account.positions([market_id]):
    sign = -1 if p['side'] == 'SHORT' else 1
    return PerpPosition(size=p['size'] * sign, entry_price=p['openPrice'])
  return PerpPosition()


{
  'mainnet': {m: await position(m) for m in MARKETS},
  'testnet': {m: await perp_position(m, on=testnet) for m in MARKETS},
}


# %% [markdown]
# ## `leverage`
#
# Fetch the leverage this account can open at on the selected market.
#
# `account.leverage`: the account's per-market setting (initial margin is `1 / leverage`, Margin Schedule docs). An account that never changed it reads the venue default, `10` on most markets and `5` on some (`AIA-USD`).


# %%
async def leverage(
  market_id: str, /, *, refetch: bool = False, on: Extended = client
) -> Decimal:
  """The account's leverage setting on the market."""
  return await account_leverage(market_id, on)


{
  'mainnet': {m: await leverage(m) for m in [*MARKETS, 'AIA-USD']},
  'testnet': {m: await leverage(m, on=testnet) for m in MARKETS},
}


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
async def collateral(
  market_id: str | None = None, /, *, on: Extended = client
) -> Collateral:
  """Defers to `perp_collateral`."""
  return await perp_collateral(market_id, on=on)


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.
#
# Extended margins at account level only (cross; no isolated mode is documented), so every market shares one bucket, `account.balance`: equity (`balance + spot equity + unrealised PnL`), free collateral `availableForTrade` (equity less margin reserved for perps and for spot buy orders), `initialMargin`, and leverage `exposure / equity`. There is no maintenance-margin figure, only `marginRatio`, documented as the sum of maintenance requirements over equity, so the requirement is `marginRatio x equity`; both accounts are flat (ratio `0`), so the ratio's unit (fraction or percent) is unconfirmed. A zero balance (the documented `404`) is `None` from the client, read as all zeros; the account stream's `BALANCE` snapshot of the same account sends exactly that.


# %%
def bucket(b: Balance | None) -> PerpCollateral:
  """The account's cross bucket; `None` is the venue's zero balance."""
  if b is None:
    zero = Decimal(0)
    return PerpCollateral(
      equity=zero,
      free_collateral=zero,
      initial_margin=zero,
      maintenance_margin=zero,
      leverage=zero,
      margin_mode='cross',
    )
  return PerpCollateral(
    equity=b['equity'],
    free_collateral=b['availableForTrade'],
    initial_margin=b['initialMargin'],
    maintenance_margin=b['marginRatio'] * b['equity'],
    leverage=b['leverage'],
    margin_mode='cross',
  )


async def perp_collateral(
  market_id: str | None = None, /, *, on: Extended = client
) -> PerpCollateral:
  """The account's one cross bucket, whatever the market."""
  return bucket(await balance(on))


async def stream_balance(on: Extended) -> Any:
  """The account stream's `BALANCE` snapshot."""
  async with on.streams.account() as stream:
    async for frame in stream:
      data = frame.get('data')
      if frame['type'] == 'BALANCE' and data is not None:
        return data.get('balance')
  raise RuntimeError('account stream closed before its balance snapshot')


mainnet_stream = await stream_balance(client)
{
  'mainnet': await collateral(),
  'mainnet ETH': await perp_collateral(ETH),
  'mainnet stream balance': {
    k: mainnet_stream[k]
    for k in ('equity', 'availableForTrade', 'initialMargin', 'marginRatio')
  },
  'testnet': await perp_collateral(on=testnet),
  'testnet ETH': await collateral(ETH, on=testnet),
}

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 343 listed perps (`ACTIVE`, `REDUCE_ONLY`, `PRELISTED`) from `info.markets`, 295 of them RFQ; the 61 `DELISTED` ones are left out (inactive ones have no book and index `0`). |
# | `depth` | verified | Order-book markets: the full REST book (BTC 3601/3697 levels, equal to the stream snapshot), `time` `None`; an inactive or unknown market has no book (`None`, MATIC-USD and NOPE-USD), which raises. RFQ markets: the first `orderbooks/rfq` snapshot, since the REST book is only indicative. |
# | `depth_stream` | verified | Snapshot, then deltas at their absolute size `c`; the minute snapshots replace the book; `seq` continuity checked. RFQ markets use the quotes stream. |
# | `tickers` | verified | One `info.markets` read: last, bid, ask, base and USD 24h volume. A `0` price maps to `None` (reduce-only MKR). No best-level sizes. RFQ bid/ask are the indicative book's. |
# | `rules` | verified | Tick, step and minimum size from `tradingConfig`; side-specific band `1 ± floor/cap` against mark; value caps in `details`; `fees=None` (no public schedule); `api` is `ACTIVE`; `fee_asset` `USD`. |
# | `fees` | verified | `account.fees` per market, symmetric by side: mainnet 0 / 2.5 bp (1 bp on 182 markets), testnet 2 / 5 bp. |
# | `candles` | verified | All six intervals through the client's `candles_paged` walk from `end`, `limit` the window's opens up to 1000 (the venue caps a request at 2800); `endTime` exclusive; a 2500-row walk (pages of 1000, 1000, 500) has no gaps or duplicates. No quote volume. |
# | `query_order` | verified | `account.order` by Extended id: a closed testnet order parses; an unknown id is `None` (the venue's bodiless `404`). Live open orders wait for testnet qualification. |
# | `open_orders` | empty | Open `LIMIT` orders, none on either account; a resting limit order would populate it. Qualification places one on testnet. |
# | `trades_history` | verified | Testnet: 4 ETH fills, per market and exchange-wide (identical). The USD fee equals value × taker rate floored to 1e-6. Order and client ids are carried. Mainnet: empty. |
# | `trades_stream` | empty | Mainnet account stream: snapshots arrive, but no fill within 10 s; a fill while subscribed would populate it. The testnet stream host answers `503`. |
# | `position` | empty | Defers to `perp_position`. |
# | `available_notional` | verified | Free collateral × leverage: testnet 994.79 × 10, mainnet 0. The margin schedule's position-value cap per leverage is not applied (design question). |
# | `place_order` | not attempted | Mapped and not run (state-changing): `LIMIT` is GTT with a 28-day expiry, `POST_ONLY` adds `postOnly`, `MARKET` is IOC bounded by `price`; RFQ markets go through `create_rfq`. Qualification: a testnet ETH post-only order far from the touch, then `query_order` and `open_orders`, and a taker round trip for fills. |
# | `cancel_order` | not attempted | Mapped, not run: `orders.cancel` by Extended id (asynchronous). Qualification: cancel the testnet order and poll `query_order` until `CANCELLED`. |
# | `cancel_orders` | not attempted | Mapped, not run: one `mass_cancel` with the ids. Qualification: two testnet limit orders cancelled together. |
# | `cancel_open_orders` | not attempted | Mapped, not run: `mass_cancel(markets=[m])`, which also cancels conditional and TP/SL orders. Qualification: orders on two testnet markets, only one market's cancelled. |
# | `index` | verified | `marketStats.indexPrice` via `info.markets([m])`, which refuses an unknown market (`market_stats` answers zeros instead). |
# | `next_funding` | verified | `fundingRate` (the one-minute estimate of the hourly rate, a fraction) and `nextFundingRate` (a time); no premium reported. |
# | `perp_stats` | verified | Bulk `info.markets`: index, mark, funding estimate and time, `openInterestBase`. No listed market reads a zero index. |
# | `funding_rates` | verified | Applied hourly rates, newest first, with inclusive ms bounds, through the client's `funding_rates_paged` walk over the 1000-row cap. BTC's full history (12 pages) comes back unique; 1547 of its rates are negative. |
# | `funding_payments` | empty | `funding_history` from `start`, per market and exchange-wide; none on either account. The received-positive sign is read from the docs and is unconfirmed. A testnet position held across the hour would populate it. |
# | `perp_position` | empty | Signed `size` by `side`, entry `openPrice`; both accounts are flat. An open testnet position would populate it. |
# | `leverage` | verified | The per-market setting: 10 (5.00 on AIA-USD). |
# | `collateral` | verified | Defers to `perp_collateral`. |
# | `perp_collateral` | verified | One cross bucket from `account.balance`: testnet equity 994.79, free `availableForTrade`. Mainnet's zero balance is `None` (the documented `404`) and matches the stream's zero snapshot. MM is `marginRatio × equity`, its unit unconfirmed while flat. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets=set(listed), assets={USD})
missing = gap('extended', ids, load_catalogue())
{
  'assets': missing.assets,
  'perp_markets': (len(missing.perp_markets), len(listed)),
  'sample': missing.perp_markets[:10],
}

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
