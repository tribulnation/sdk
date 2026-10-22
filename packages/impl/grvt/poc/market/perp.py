# %% [markdown]
# # grvt `market` PoC (perp)
#
# Maps `typed_grvt` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.
#
# Two clients, one per GRVT environment:
#
# 1. `client`: **mainnet**, the read-only API key (`GRVT_API_KEY`, `GRVT_TRADING_ACCOUNT_ID`; no private key, no funds). Every read runs here.
# 2. `testnet`: **testnet** (`GRVT_TESTNET_*`), funded and allowed to trade. The user authorized testnet trading for this PoC: tiny post-only orders far below the market, each meeting the instrument's `min_notional`, cancelled by their own client order ids, nothing left open. Every state-changing helper refuses any other host (`require_testnet`). Account reads are also run against testnet where the mainnet account has nothing to show.
#
# IDs are the venue's own: market ids are instrument names (`BTC_USDT_Perp`), the same on both environments; asset ids are currency codes (`USDT`). Every perpetual is USDT-quoted and USDT-margined.

# %%
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal
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
import secrets

from dotenv import load_dotenv
from typed_grvt import BadRequest, Grvt
from typed_grvt.schemas import (
  Candlestick,
  CandlestickInterval,
  Fill,
  InstrumentDisplay,
  NewOrder,
  Order as GrvtOrder,
  OrderbookLevel,
  Ticker as GrvtTicker,
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

load_dotenv()

stack = AsyncExitStack()
client = await stack.enter_async_context(Grvt.new())
testnet = await stack.enter_async_context(Grvt.new(env='testnet'))

TESTNET_TRADES = 'https://trades.testnet.grvt.io'
MARKETS = ['BTC_USDT_Perp', 'ETH_USDT_Perp', 'AAPL_USDT_Perp', 'XAU_USDT_Perp']
"""A crypto, a second crypto, an equity and a commodity perpetual."""
BTC = 'BTC_USDT_Perp'
ETH = 'ETH_USDT_Perp'
PERCENT = Decimal(100)
FEE_UNIT = Decimal('1e-6')
"""`ClientTier` fee rates are integers in millionths of notional (GRVT's "centibeeps"): tier 1's
`450` is the 0.045% taker rate of the published schedule, and testnet fills at that tier
report `fee_rate` `0.045` (percent)."""

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)


def require_testnet(c: Grvt):
  """Refuse any state-changing call outside GRVT testnet."""
  if c.trading_client.base_url != TESTNET_TRADES:
    raise RuntimeError('This PoC may only change state on GRVT testnet')


async def instruments(c: Grvt = client) -> dict[str, InstrumentDisplay]:
  """Every perpetual, delisted ones included, keyed by instrument name."""
  return {
    i['instrument']: i for i in await c.market.all_instruments(kinds=['PERPETUAL'])
  }


INSTRUMENTS = await instruments()
TESTNET_INSTRUMENTS = await instruments(testnet)
(
  version('typed-grvt'),
  len(INSTRUMENTS),
  len(TESTNET_INSTRUMENTS),
  {m: INSTRUMENTS[m].get('status') for m in MARKETS},
)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_grvt',
    'Grvt',
    grep=r'^market\.(all_instruments|instrument|orderbook|ticker|mini_ticker|candlesticks|funding_rate|margin_rules|collateral_asset_info)|^market_streams\.orderbook|^trading\.(account_summary|funding_account_summary|all_initial_leverage|positions|open_orders|order|create_order|cancel_order|cancel_all_orders|bulk_orders|fill_history|funding_payment_history)|^trading_streams\.fills',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.
#
# Every `PERPETUAL` instrument, delisted ones included (`rules().api` says whether it trades). `STABLE_PERP` (GRVT's RFQ-traded stable perpetuals, multi-asset mode only) is a different product and left out; neither environment lists one today.


# %%
async def markets(c: Grvt = client) -> Sequence[str]:
  """Every perpetual's instrument name."""
  return list(await instruments(c))


listed = await markets()
{
  'mainnet': (
    len(listed),
    Counter(INSTRUMENTS[m].get('status') for m in listed),
    Counter(INSTRUMENTS[m].get('asset_class') for m in listed),
    Counter(INSTRUMENTS[m]['quote'] for m in listed),
  ),
  'testnet only': sorted(set(await markets(testnet)) - set(listed)),
  'one perpetual per base/quote': len({(i['base'], i['quote']) for i in INSTRUMENTS.values()})
  == len(INSTRUMENTS),
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.
#
# `orderbook` takes a depth of 10, 50, 100 or 500 levels per side: the smallest one covering `levels`, else 500. 500 covers the whole book of every market sampled (BTC returns fewer than 500 levels per side).

# %%
DEPTHS: tuple[Literal[10, 50, 100, 500], ...] = (10, 50, 100, 500)


def venue_depth(levels: int | None) -> Literal[10, 50, 100, 500]:
  """The smallest venue depth covering `levels`, else the largest."""
  for d in DEPTHS:
    if levels is not None and d >= levels:
      return d
  return DEPTHS[-1]


def entries(levels: Sequence[OrderbookLevel]) -> list[Book.Entry]:
  """Book entries from venue levels."""
  return [Book.Entry(level['price'], level['size']) for level in levels]


async def depth(
  market_id: str, /, *, levels: int | None = None, settings: Settings = {}
) -> Book:
  """The aggregated book, at the smallest venue depth covering `levels`."""
  book = await client.market.orderbook(market_id, depth=venue_depth(levels))
  result = Book(
    bids=entries(book['bids']), asks=entries(book['asks']), time=book['event_time']
  )
  return result.limit(levels) if levels is not None else result


books = {m: await depth(m) for m in MARKETS}
{
  'full': {
    m: (len(b.bids), len(b.asks), b.best_bid.price, b.best_ask.price, b.time)
    for m, b in books.items()
  },
  'levels=3': await depth(BTC, levels=3),
}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.
#
# `v1.book.d` sends the full book on subscribe (`num_snapshots` frames, sequence `0`), then changed levels (size `0` deletes one) at most every 50 ms. The client checks sequence continuity itself and ends the stream with `NetworkError` on a gap, so the mapping only applies frames.


# %%
@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
  settings: Settings = {},
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Maintain a local book from the snapshot and its deltas."""
  async with client.market_streams.orderbook_delta(market_id, rate=50) as stream:
    snapshots = stream.reply['num_snapshots'][0]

    async def books():
      book = Book()
      received = 0
      async for frame in stream:
        update = Book(
          bids=entries(frame['bids']),
          asks=entries(frame['asks']),
          time=frame['event_time'],
        )
        if received == 0:
          book = update
        else:
          book.update(update)
        received += 1
        if received >= snapshots:
          yield book.limit(levels) if levels is not None else book.copy()

    yield books()


seen: list[tuple[int, int, Decimal, Decimal, bool]] = []
async with depth_stream(BTC) as stream:
  async for update in stream:
    seen.append(
      (
        len(update.bids),
        len(update.asks),
        update.best_bid.price,
        update.best_ask.price,
        update.best_bid.price < update.best_ask.price,
      )
    )
    if len(seen) == 20:
      break
{'first': seen[0], 'last': seen[-1], 'uncrossed': all(s[4] for s in seen)}


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.
#
# GRVT has no bulk ticker: one `ticker` per instrument, sent concurrently over the market-data WebSocket (all 194 take well under a second). The venue sends `0` for the price and size of an empty book side (delisted instruments), which maps to `None`. The 24 h volumes are the taker buy plus taker sell volumes (every trade has exactly one taker), checked below against the sum of the day's one-minute candles.


# %%
def price_or_none(value: Decimal | None) -> Decimal | None:
  """A ticker price, or `None` where the venue sends `0` (an empty side) or nothing."""
  return value if value else None


def volume(buy: Decimal | None, sell: Decimal | None) -> Decimal | None:
  """Taker buy plus taker sell volume, or `None` if either is missing."""
  return None if buy is None or sell is None else buy + sell


def parse_ticker(t: GrvtTicker) -> Ticker:
  """An SDK ticker from a venue ticker."""
  bid = price_or_none(t.get('best_bid_price'))
  ask = price_or_none(t.get('best_ask_price'))
  return Ticker(
    last=price_or_none(t.get('last_price')),
    bid=bid,
    ask=ask,
    bid_qty=t.get('best_bid_size') if bid is not None else None,
    ask_qty=t.get('best_ask_size') if ask is not None else None,
    base_volume_24h=volume(t.get('buy_volume_24h_b'), t.get('sell_volume_24h_b')),
    quote_volume_24h=volume(t.get('buy_volume_24h_q'), t.get('sell_volume_24h_q')),
  )


async def venue_tickers(names: Collection[str]) -> dict[str, GrvtTicker]:
  """One venue ticker per instrument, fetched concurrently over the WebSocket."""
  wanted = [n for n in names if n in INSTRUMENTS]
  rows = await asyncio.gather(
    *[client.market.ticker(n, transport='ws') for n in wanted]
  )
  return dict(zip(wanted, rows))


async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Tickers for the given markets, or every listed one."""
  names = INSTRUMENTS.keys() if markets is None else markets
  return {m: parse_ticker(t) for m, t in (await venue_tickers(names)).items()}


everything = await tickers()
delisted = [m for m, i in INSTRUMENTS.items() if i.get('status') == 'DELISTED']
{
  'all': len(everything),
  'selected': await tickers(MARKETS),
  'delisted': everything[delisted[0]] if delisted else None,
  'empty': await tickers([]),
}

# %%
# The 24h volume check: buy + sell against the sum of the last 1440 one-minute candles.
day_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
minute_rows = [
  c
  async for page in client.market.candlesticks_paged(
    BTC,
    interval='CI_1_M',
    type='TRADE',
    start_time=day_end - timedelta(days=1),
    end_time=day_end,
    limit=1000,
  )
  for c in page
]
btc_ticker = (await tickers([BTC]))[BTC]
{
  'ticker base/quote': (btc_ticker.base_volume_24h, btc_ticker.quote_volume_24h),
  'candles base/quote': (
    sum((c['volume_b'] for c in minute_rows), Decimal(0)),
    sum((c['volume_q'] for c in minute_rows), Decimal(0)),
  ),
  'candles': len(minute_rows),
}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.
#
# From the instrument: `tick_size`, `min_size` (also the size step: a post-only order `min_size / 2` off the grid is refused with `2065` *Order size too granular*, an off-tick price with `2064`; see `place_order`), and `min_notional`. `max_position_size` caps a position, not an order, so it stays in `details`. `api` is `status == 'ACTIVE'`.
#
# Fees: the API publishes no standard schedule; the account's own tier is account data (`fees`). `STANDARD_FEES` is tier 1 of the schedule GRVT publishes (help.grvt.io, *How does Grvt's Fee Model work?*, read 2026-10-22: perps maker -0.0001%, taker 0.0450%), which is also what the API reports as tier 1 (`450`/`-1` millionths) on both environments. Fees are charged in USDT, the quote and settlement currency (every testnet fill's `fee_currency`).

# %%
STANDARD_FEES = Fees.symmetric(maker=Decimal('-0.000001'), taker=Decimal('0.00045'))
"""GRVT's published tier-1 perpetual rates (help.grvt.io fee model, read 2026-10-22)."""


async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Increments, floors and the published standard rates."""
  i = (await instruments())[market_id] if refetch else INSTRUMENTS[market_id]
  return Rules(
    fee_asset=i['quote'],
    tick_size=i['tick_size'],
    step_size=i['min_size'],
    fixed_min_qty=i['min_size'],
    min_value=i['min_notional'],
    fees=STANDARD_FEES,
    api=i.get('status') == 'ACTIVE',
    details=i,
  )


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.
#
# `funding_account_summary` carries the account's `ClientTier`: futures maker and taker rates in millionths of notional (`FEE_UNIT`), the same for every perpetual and both sides. The unit is not documented by GRVT; it is fixed by the published schedule (tier 1 is 0.045% taker, -0.0001% maker) and by testnet taker fills, whose `fee_rate` (percent) and `fee` match it exactly (below).


# %%
async def fees(market_id: str, /, *, refetch: bool = False, on: Grvt = client) -> Fees:
  """The account tier's futures maker and taker rates."""
  tier = (await on.trading.funding_account_summary())['tier']
  return Fees.symmetric(
    maker=tier['futures_maker_fee'] * FEE_UNIT,
    taker=tier['futures_taker_fee'] * FEE_UNIT,
  )


async def tier_of(c: Grvt) -> tuple[int, int, int]:
  """The account's tier and its futures maker/taker integers."""
  tier = (await c.trading.funding_account_summary())['tier']
  return tier['tier'], tier['futures_maker_fee'], tier['futures_taker_fee']


testnet_fills = await testnet.trading.fill_history(kind=['PERPETUAL'], limit=20)
testnet_taker = (await fees(BTC, on=testnet)).taker_buy
{
  'mainnet tier': await tier_of(client),
  'mainnet fees': await fees(BTC),
  'testnet tier': await tier_of(testnet),
  'testnet fills (maker?, fee_rate %, fee, notional x taker rate)': [
    (
      not f['is_taker'],
      f['fee_rate'],
      f['fee'],
      f['size'] * f['price'] * testnet_taker,
      f['fee_currency'],
    )
    for f in testnet_fills['result'][:6]
  ],
}


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.
#
# `candlesticks_paged` (type `TRADE`), newest first; the client walks pages by moving `end_time` to the oldest open received. The venue's bounds are inclusive on open time at both ends (a `[06:11, 06:16]` request returned six one-minute candles), so the SDK's exclusive `end` is applied locally. At most 1000 rows per request.

# %%
INTERVALS: dict[CandleInterval, CandlestickInterval] = {
  '1m': 'CI_1_M',
  '5m': 'CI_5_M',
  '15m': 'CI_15_M',
  '1h': 'CI_1_H',
  '4h': 'CI_4_H',
  '1d': 'CI_1_D',
}


def parse_candle(c: Candlestick) -> Candle:
  """An SDK candle from a venue candlestick."""
  return Candle(
    time=c['open_time'],
    open=c['open'],
    high=c['high'],
    low=c['low'],
    close=c['close'],
    volume=c['volume_b'],
    quote_volume=c['volume_q'],
    trades=c['trades'],
  )


async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Candles opening in `[start, end)`, newest first."""
  if end <= start:
    return
  pages = client.market.candlesticks_paged(
    market_id,
    interval=INTERVALS[interval],
    type='TRADE',
    start_time=start,
    end_time=end,
    limit=1000,
  )
  async for page in pages:
    rows = [parse_candle(c) for c in page if start <= c['open_time'] < end]
    if rows:
      yield rows


candle_end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
widths = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
probe: dict[str, Any] = {}
for interval in INTERVALS:
  window_end = candle_end.replace(hour=0) if interval == '1d' else candle_end
  window_start = window_end - timedelta(minutes=widths[interval] * 5)
  rows = [
    c async for page in candles(BTC, interval, window_start, window_end) for c in page
  ]
  probe[interval] = (len(rows), min(c.time for c in rows), max(c.time for c in rows))
probe['equal bounds'] = [
  c async for page in candles(BTC, '1m', candle_end, candle_end) for c in page
]
probe['other markets 1h'] = {
  m: len(
    [
      c
      async for page in candles(m, '1h', candle_end - timedelta(hours=5), candle_end)
      for c in page
    ]
  )
  for m in MARKETS
}
probe

# %%
# Cross-page: 2500 one-minute candles walk three pages with no duplicates or gaps.
cross_start = candle_end - timedelta(minutes=2500)
pages = [page async for page in candles(BTC, '1m', cross_start, candle_end)]
times = sorted(c.time for page in pages for c in page)
{
  'pages': [len(p) for p in pages],
  'unique': len(set(times)) == len(times),
  'first': times[0],
  'last': times[-1],
  'missing_minutes': 2500 - len(times),
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.
#
# The SDK order id is the order's `client_order_id`: `create_order` answers `PENDING` with the placeholder `order_id` `0x00` (the venue assigns the real one when it processes the order), while `order` and `cancel_order` both accept a client order id, and fills report it. An unknown id answers `1004` *Data Not Found* (`BadRequest`), which maps to `None`. Cancelled orders stay queryable. Exercised on live testnet orders in the trading cells below.

# %%
ACTIVE = {'PENDING', 'OPEN'}


def parse_order(o: GrvtOrder) -> OrderState:
  """An SDK order state from a single-leg venue order; sells are negative."""
  leg = o['legs'][0]
  sign = 1 if leg['is_buying_asset'] else -1
  state = o.get('state')
  traded = (state['traded_size'] if state is not None else None) or [Decimal(0)]
  return OrderState(
    id=o['metadata']['client_order_id'],
    price=leg.get('limit_price', Decimal(0)),
    qty=sign * leg['size'],
    filled_qty=sign * traded[0],
    active=state is not None and state['status'] in ACTIVE,
    details=o,
  )


async def query_order(
  market_id: str, /, id: str, *, on: Grvt = client
) -> OrderState | None:
  """Look the order up by client order id."""
  try:
    o = await on.trading.order({'client_order_id': id})
  except BadRequest as e:
    if e.args and e.args[0] == 1004:
      return None
    raise
  if o['legs'][0]['instrument'] != market_id:
    return None
  return parse_order(o)


def random_client_order_id() -> str:
  """A client order id in the range GRVT reserves for API clients, [2^63, 2^64)."""
  return str(2**63 + secrets.randbelow(2**63))


{
  'mainnet missing': await query_order(BTC, random_client_order_id()),
  'testnet missing': await query_order(BTC, random_client_order_id(), on=testnet),
}


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.
#
# `open_orders` filters by kind, base and quote, never by instrument; each perpetual is the only one of its base and quote (checked in `markets`), so the filter is exact. Exercised on live testnet orders in the trading cells below.


# %%
def scope(market_id: str) -> tuple[list[str], list[str]]:
  """The base and quote filters naming one perpetual."""
  i = INSTRUMENTS[market_id]
  return [i['base']], [i['quote']]


async def open_orders(market_id: str, /, *, on: Grvt = client) -> Sequence[OrderState]:
  """The market's open orders."""
  base, quote = scope(market_id)
  rows = await on.trading.open_orders(kind=['PERPETUAL'], base=base, quote=quote)
  return [parse_order(o) for o in rows if o['legs'][0]['instrument'] == market_id]


{
  'mainnet': {m: await open_orders(m) for m in MARKETS},
  'testnet': {m: await open_orders(m, on=testnet) for m in (BTC, ETH)},
}


# %% [markdown]
# ## `trades_history`
#
# Fetch personal fills for one market or the whole exchange.
#
# `fill_history_paged`, newest first, scoped like `open_orders` (or by kind only, exchange-wide). `id` is the venue's `trade_id`; `order_id` and `client_order_id` are both the order's client order id (the SDK order id). The fee is the venue's `fee` in `fee_currency` (negative for a maker rebate); a builder fee, when an order names a builder, is a separate `builder_fee` and is not added. Bounds are the venue's `start_time`/`end_time`, applied by the venue in nanoseconds while `typed-grvt`'s datetimes carry microseconds: a fill's own reported time used as `end` excludes it (the 7/7/8 counts below), so an implementation sends `end` plus one microsecond and filters locally. The mainnet account has no fills, so the mapping is checked on testnet's.


# %%
def parse_fill(f: Fill) -> Trade:
  """An SDK trade from a venue fill."""
  return Trade(
    id=f['trade_id'],
    order_id=f['client_order_id'],
    client_order_id=f['client_order_id'],
    price=f['price'],
    qty=f['size'] if f['is_buyer'] else -f['size'],
    time=f['event_time'],
    maker=not f['is_taker'],
    fee=Trade.Fee(amount=f['fee'], asset=f['fee_currency']),
    details=f,
  )


async def trades_history(
  market_id: str | None, /, start: datetime, end: datetime, *, on: Grvt = client
) -> AsyncIterable[Sequence[Trade]]:
  """Personal perpetual fills between `start` and `end`, newest first."""
  if market_id is None:
    pages = on.trading.fill_history_paged(
      kind=['PERPETUAL'], start_time=start, end_time=end, limit=1000
    )
  else:
    base, quote = scope(market_id)
    pages = on.trading.fill_history_paged(
      kind=['PERPETUAL'],
      base=base,
      quote=quote,
      start_time=start,
      end_time=end,
      limit=1000,
    )
  async for page in pages:
    if market_id is None:
      yield [
        ExchangeTrade(**vars(parse_fill(f)), market_id=f['instrument']) for f in page
      ]
    else:
      yield [parse_fill(f) for f in page if f['instrument'] == market_id]


def brief(t: Trade) -> tuple[Any, ...]:
  """The fields under test, without the raw payload."""
  return (t.id, t.client_order_id, t.price, t.qty, t.time, t.maker, t.fee)


history_start = end - timedelta(days=30)
mainnet_history = {
  m: [t async for page in trades_history(m, history_start, end) for t in page]
  for m in MARKETS
}
testnet_btc = [
  t async for page in trades_history(BTC, history_start, end, on=testnet) for t in page
]
testnet_all = [
  t async for page in trades_history(None, history_start, end, on=testnet) for t in page
]
newest = next((t.time for t in testnet_btc if t.time is not None), end)
{
  'mainnet': {m: len(ts) for m, ts in mainnet_history.items()},
  'testnet BTC': (len(testnet_btc), [brief(t) for t in testnet_btc[:3]]),
  'testnet exchange': (
    len(testnet_all),
    Counter(t.market_id for t in testnet_all if isinstance(t, ExchangeTrade)),
  ),
  'ids unique': len({t.id for t in testnet_all}) == len(testnet_all),
  'newest fill time': newest,
  'count with end at newest -1 ms / newest / +1 us': [
    len(
      [
        t
        async for page in trades_history(BTC, history_start, bound, on=testnet)
        for t in page
      ]
    )
    for bound in (
      newest - timedelta(milliseconds=1),
      newest,
      newest + timedelta(microseconds=1),
    )
  ],
}

# %%
# Pagination: the same testnet window, two fills per page.
small_pages = [
  [f['trade_id'] for f in page]
  async for page in testnet.trading.fill_history_paged(
    kind=['PERPETUAL'], start_time=history_start, end_time=end, limit=2
  )
]
{
  'pages': [len(p) for p in small_pages],
  'same fills': sorted(i for p in small_pages for i in p)
  == sorted(t.id or '' for t in testnet_all),
}


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.
#
# `v1.fill` for the instrument (the client fills the sub-account selector). It pushes the same `Fill` the history returns, so `parse_fill` maps both. No fill happens in the cell below (resting orders only); the testnet round trip near the end streams both of its fills.


# %%
@asynccontextmanager
async def trades_stream(
  market_id: str,
  /,
  *,
  queue_size: int = 1000,
  overflow: OverflowPolicy = 'fail',
  settings: Settings = {},
  on: Grvt = client,
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """The account's new fills on one market."""
  async with on.trading_streams.fills(instrument=market_id) as stream:

    async def trades():
      async for fill in stream:
        yield parse_fill(fill)

    yield trades()


async def first_trade(c: Grvt) -> Trade | str:
  """The first streamed fill within five seconds, else what happened."""
  async with trades_stream(BTC, on=c) as stream:
    try:
      return await asyncio.wait_for(anext(aiter(stream)), 5)
    except asyncio.TimeoutError:
      return 'subscribed; no fill within 5 s'


{'mainnet': await first_trade(client), 'testnet': await first_trade(testnet)}


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market (defers to `perp_position`, below).


# %%
async def position(market_id: str, /) -> Position:
  """Defers to `perp_position`."""
  return await perp_position(market_id)


# %% [markdown]
# ## `available_notional`
#
# Fetch the maximum notional position you can open right now.
#
# The SDK default: cross free collateral (`perp_collateral`) times the market's leverage (`leverage`). GRVT also caps a position at `max_position_size` (base units) and lowers the maximum leverage by risk bracket as the notional grows (`margin_rules`); neither is applied here. Exercised after `perp_collateral`, which it calls.


# %%
async def available_notional(market_id: str, /, *, on: Grvt = client) -> Decimal:
  """Free cross collateral times the market's leverage."""
  free = (await perp_collateral(on=on)).free_collateral
  return free * await leverage(market_id, on=on)


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.
#
# **Testnet only.** One leg on the instrument; the SDK id is the order's client order id: the caller's `Order['client_order_id']`, sent unchanged, else a fresh one in [2^63, 2^64). `LIMIT` is `GOOD_TILL_TIME`, `POST_ONLY` adds `post_only`, `MARKET` is the venue's market order (`is_market`, `IMMEDIATE_OR_CANCEL`), which refuses a limit price (`2020`), so the SDK price is not sent. A `GOOD_TILL_TIME` order expires with its signature: the client's `signature_ttl`, one day by default and at most 30. The reply is the order as accepted: `PENDING`, `order_id` `0x00`, nothing filled yet. A malformed order is refused before it exists (`BadRequest`: `2064` off-tick price, `2065` size off the step); a refusal after acceptance (`FAIL_POST_ONLY`, margin) only shows as a `REJECTED` state.
#
# Executed: post-only buys 40% below the market. `LIMIT` was not sent; `MARKET` is exercised by the testnet round trip near the end (same mapping, `market_order`).


# %%
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}, on: Grvt = testnet
) -> OrderResponse:
  """Sign and send a single-leg order; its client order id is the SDK id."""
  require_testnet(on)
  qty = Decimal(str(order['qty']))
  client_order_id = order.get('client_order_id') or random_client_order_id()
  if order['type'] == 'MARKET':
    new: NewOrder = {
      'is_market': True,
      'time_in_force': 'IMMEDIATE_OR_CANCEL',
      'metadata': {'client_order_id': client_order_id},
      'legs': [{'instrument': market_id, 'size': abs(qty), 'is_buying_asset': qty > 0}],
    }
  else:
    new = {
      'time_in_force': 'GOOD_TILL_TIME',
      'post_only': order['type'] == 'POST_ONLY',
      'metadata': {'client_order_id': client_order_id},
      'legs': [
        {
          'instrument': market_id,
          'size': abs(qty),
          'limit_price': Decimal(str(order['price'])),
          'is_buying_asset': qty > 0,
        }
      ],
    }
  reply = await on.trading.create_order(new)
  return OrderResponse(id=client_order_id, details=reply)


def far_buy(market_id: str, bid: Decimal) -> Order:
  """A post-only buy 40% below `bid`, sized to clear `min_notional` by one step."""
  i = TESTNET_INSTRUMENTS[market_id]
  price = (bid * Decimal('0.6')).quantize(i['tick_size'])
  steps = (i['min_notional'] / price / i['min_size']).to_integral_value(ROUND_UP) + 1
  return {'type': 'POST_ONLY', 'qty': steps * i['min_size'], 'price': price}


def narrowed(o: GrvtOrder) -> dict[str, Any]:
  """The fields under test, without the signature or account ids."""
  return {
    'order_id': o.get('order_id'),
    'client_order_id': o['metadata']['client_order_id'],
    'post_only': o.get('post_only'),
    'legs': o['legs'],
    'state': o.get('state'),
  }


async def testnet_bid(market_id: str) -> Decimal:
  """The testnet best bid."""
  bid = (await testnet.market.ticker(market_id)).get('best_bid_price')
  if not bid:
    raise RuntimeError(f'No testnet bid on {market_id}')
  return bid


btc_bid = await testnet_bid(BTC)
mine: set[str] = set()
"""Client order ids this PoC placed on testnet."""
resting = await place_order(BTC, far_buy(BTC, btc_bid))
mine.add(resting.id)
refused: dict[str, Any] = {}
for label, change in (('off-tick price', 'price'), ('off-step size', 'qty')):
  bad = far_buy(BTC, btc_bid)
  i = TESTNET_INSTRUMENTS[BTC]
  if change == 'price':
    bad['price'] = Decimal(str(bad['price'])) + i['tick_size'] / 2
  else:
    bad['qty'] = Decimal(str(bad['qty'])) + i['min_size'] / 2
  bad_id = random_client_order_id()
  bad['client_order_id'] = bad_id
  mine.add(bad_id)
  try:
    refused[label] = await place_order(BTC, bad)
  except BadRequest as e:
    refused[label] = f'BadRequest {e.args[:2]}'
await asyncio.sleep(2)
looked_up = await query_order(BTC, resting.id, on=testnet)
{
  'reply': narrowed(resting.details),
  'query': (looked_up.id, looked_up.price, looked_up.qty, looked_up.active)
  if looked_up
  else None,
  'venue order_id': looked_up.details.get('order_id') if looked_up else None,
  'open_orders': [o.id for o in await open_orders(BTC, on=testnet)],
  'refused': refused,
}


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.
#
# **Testnet only.** By client order id. The venue acknowledges any id, known or not (`{'ack': True}`: a cancel by client order id also arms a short time-to-live against an order still in flight), so the outcome is read back with `query_order`.


# %%
async def cancel_order(
  market_id: str, /, id: str, *, settings: Settings = {}, on: Grvt = testnet
) -> Any:
  """Cancel by client order id."""
  require_testnet(on)
  return await on.trading.cancel_order({'client_order_id': id})


ack = await cancel_order(BTC, resting.id)
await asyncio.sleep(2)
cancelled = await query_order(BTC, resting.id, on=testnet)
{
  'ack': ack,
  'state': cancelled.details.get('state') if cancelled else None,
  'active': cancelled.active if cancelled else None,
  'open_orders': [o.id for o in await open_orders(BTC, on=testnet)],
}


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.
#
# **Testnet only.** `bulk_orders` with `client_order_i_ds` (the venue's own spelling), up to 100 per request.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}, on: Grvt = testnet
) -> Any:
  """Bulk cancel by client order id, 100 per request."""
  require_testnet(on)
  return [
    await on.trading.bulk_orders({'client_order_i_ds': list(ids[i : i + 100])})
    for i in range(0, len(ids), 100)
  ]


pair = [await place_order(BTC, far_buy(BTC, btc_bid)) for _ in range(2)]
mine.update(p.id for p in pair)
await asyncio.sleep(2)
opened = [o.id for o in await open_orders(BTC, on=testnet)]
acks = await cancel_orders(BTC, [p.id for p in pair])
await asyncio.sleep(2)
{
  'placed': [p.id in opened for p in pair],
  'acks': [a['cancel_acks'] for a in acks],
  'after': [o.id for o in await open_orders(BTC, on=testnet)],
  'states': [
    s.details['state']['status']
    for p in pair
    if (s := await query_order(BTC, p.id, on=testnet))
  ],
}


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.
#
# **Testnet only.** `cancel_all_orders` scoped like `open_orders`: kind `PERPETUAL` and the market's base and quote, which name exactly one market. Before it runs, every open order on the account must be one this PoC placed. Two BTC orders and one ETH order: only BTC's are cancelled, then the ETH order is cancelled by id.


# %%
async def cancel_open_orders(
  market_id: str, /, *, settings: Settings = {}, on: Grvt = testnet
) -> Any:
  """The venue's cancel-all, scoped to one perpetual."""
  require_testnet(on)
  base, quote = scope(market_id)
  return await on.trading.cancel_all_orders(kind=['PERPETUAL'], base=base, quote=quote)


btc_orders = [await place_order(BTC, far_buy(BTC, btc_bid)) for _ in range(2)]
eth_order = await place_order(ETH, far_buy(ETH, await testnet_bid(ETH)))
mine.update([*(o.id for o in btc_orders), eth_order.id])
await asyncio.sleep(2)
everyone = [o['metadata']['client_order_id'] for o in await testnet.trading.open_orders()]
if not set(everyone) <= mine:
  raise RuntimeError('The testnet account has open orders this PoC did not place')
before = {m: [o.id for o in await open_orders(m, on=testnet)] for m in (BTC, ETH)}
await cancel_open_orders(BTC)
await asyncio.sleep(2)
after = {m: [o.id for o in await open_orders(m, on=testnet)] for m in (BTC, ETH)}
await cancel_order(ETH, eth_order.id)
await asyncio.sleep(2)
{
  'before': {m: len(ids) for m, ids in before.items()},
  'after BTC cancel-all': {m: len(ids) for m, ids in after.items()},
  'eth survived': after[ETH] == [eth_order.id],
  'left open on the account': len(await testnet.trading.open_orders()),
}


# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  """The mini ticker's `index_price`."""
  price = (await client.market.mini_ticker(market_id)).get('index_price')
  if price is None:
    raise ValueError(f'No index price for {market_id}')
  return price


{m: await index(m) for m in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.
#
# The ticker's `funding_rate`, the indicative rate of the interval ending at `next_funding_time`, in percentage points (the typed client and GRVT's schema docs say centibeeps; see the unit check below). The interval is the instrument's `funding_interval_hours` (8 h or 4 h; the ticker never sends its own). Positive means longs pay shorts (GRVT's *Funding Rate Mechanism*). No premium is published.


# %%
def funding_of(t: GrvtTicker, i: InstrumentDisplay) -> NextFunding:
  """The indicative rate of the current interval."""
  rate, time, hours = (
    t.get('funding_rate'),
    t.get('next_funding_time'),
    i.get('funding_interval_hours'),
  )
  if rate is None or time is None or hours is None:
    raise ValueError(f'No funding data for {i["instrument"]}')
  return NextFunding(rate=rate / PERCENT, time=time, interval=timedelta(hours=hours))


async def next_funding(market_id: str, /) -> NextFunding:
  """From the market's ticker and instrument."""
  return funding_of(await client.market.ticker(market_id), INSTRUMENTS[market_id])


{m: await next_funding(m) for m in MARKETS}

# %%
# Unit check: indicative rates against each market's last settled rate (percent) and cap.
latest = {
  m: (await client.market.funding_rate(instrument=m, limit=1))['result'][0]
  for m in MARKETS
}
venue = await venue_tickers(MARKETS)
{
  m: {
    'indicative': venue[m].get('funding_rate'),
    'last settled': latest[m]['funding_rate'],
    'cap': INSTRUMENTS[m].get('adjusted_funding_rate_cap'),
    'deprecated 8h_curr': venue[m].get('funding_rate_8h_curr'),
  }
  for m in MARKETS
}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.
#
# The same concurrent tickers as `tickers`: index, mark, indicative funding (as in `next_funding`) and open interest in base units.


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Index, mark, indicative funding and open interest per market."""
  names = INSTRUMENTS.keys() if markets is None else markets
  stats: dict[str, PerpStats] = {}
  for m, t in (await venue_tickers(names)).items():
    index_price = t.get('index_price')
    if index_price is None:
      continue
    funding = funding_of(t, INSTRUMENTS[m])
    stats[m] = PerpStats(
      index=index_price,
      mark=t.get('mark_price'),
      funding=funding.rate,
      next_funding_time=funding.time,
      funding_interval=funding.interval,
      open_interest=t.get('open_interest'),
    )
  return stats


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
# `funding_rate_paged`, newest first, `funding_rate` in percentage points at `funding_time`. The venue's bounds are inclusive at both ends, as the SDK's are. From 2025-10-15 16:00 UTC (BTC) each row is one settlement (`funding_interval_hours` 8 or 4); up to 2025-10-15 08:00 the venue returns one row per minute with `funding_interval_hours` `0` (about 1435 a day, probe below), so an unbounded walk (`start=None`) reads every minute of the older history.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Funding rows with `start <= time <= end`, newest first."""
  pages = client.market.funding_rate_paged(
    instrument=market_id, start_time=start, end_time=end, limit=1000
  )
  async for page in pages:
    yield [
      FundingRate(rate=r['funding_rate'] / PERCENT, time=r['funding_time']) for r in page
    ]


rates = {
  m: [r async for page in funding_rates(m, end - timedelta(days=2), end) for r in page]
  for m in MARKETS
}
settled = rates[BTC][1].time
exact = [r async for page in funding_rates(BTC, settled, settled) for r in page]
{
  'counts': {m: len(rs) for m, rs in rates.items()},
  'latest': {m: rs[0] for m, rs in rates.items()},
  'signs': Counter(r.rate > 0 for rs in rates.values() for r in rs),
  'exact bounds': exact,
  'open bounds': [
    r
    async for page in funding_rates(
      BTC, settled + timedelta(microseconds=1), settled + timedelta(hours=8, microseconds=-1)
    )
    for r in page
  ],
}

# %%
# The regime change: BTC rows between 2025-10-15 07:57 and 16:00 UTC, with their funding_interval_hours.
around = await client.market.funding_rate(
  instrument=BTC,
  start_time=datetime(2025, 10, 15, 7, 57, tzinfo=timezone.utc),
  end_time=datetime(2025, 10, 15, 16, tzinfo=timezone.utc),
)
[
  (r['funding_time'], r['funding_rate'], r['funding_interval_hours'])
  for r in around['result']
]


# %% [markdown]
# ## `funding_payments`
#
# Fetch personal funding payments for one market or the whole exchange.
#
# `funding_payment_history_paged`, by instrument or exchange-wide (kind `PERPETUAL`). The venue's `amount` is positive when paid and negative when received (the field's own documentation, and `Position.cumulative_realized_funding_payment` likewise), so it is negated into the SDK's received-positive cash flow. Neither account has a payment in the cell below; the testnet funding position near the end received one, confirming the sign.


# %%
async def funding_payments(
  market_id: str | None, /, start: datetime, end: datetime, *, on: Grvt = client
) -> AsyncIterable[Sequence[FundingPayment]]:
  """Personal funding payments between `start` and `end`, newest first."""
  if market_id is None:
    pages = on.trading.funding_payment_history_paged(
      kind=['PERPETUAL'], start_time=start, end_time=end, limit=1000
    )
  else:
    pages = on.trading.funding_payment_history_paged(
      instrument=market_id, start_time=start, end_time=end, limit=1000
    )
  async for page in pages:
    if market_id is None:
      yield [
        ExchangeFundingPayment(
          amount=-p['amount'], time=p['event_time'], market_id=p['instrument']
        )
        for p in page
      ]
    else:
      yield [FundingPayment(amount=-p['amount'], time=p['event_time']) for p in page]


payments_start = end - timedelta(days=30)
{
  env: {
    'per market': {
      m: [p async for page in funding_payments(m, payments_start, end, on=c) for p in page]
      for m in (BTC, ETH)
    },
    'exchange': [
      p async for page in funding_payments(None, payments_start, end, on=c) for p in page
    ],
  }
  for env, c in (('mainnet', client), ('testnet', testnet))
}


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.
#
# `positions` scoped like `open_orders`: `size` is signed, `entry_price` the average entry. No position means flat. Both accounts are flat here; the testnet round trip and funding position near the end hold positions (0.002 BTC, 234 BARD).


# %%
async def perp_position(market_id: str, /, *, on: Grvt = client) -> PerpPosition:
  """The account's signed position and average entry."""
  base, quote = scope(market_id)
  rows = await on.trading.positions(kind=['PERPETUAL'], base=base, quote=quote)
  for p in rows:
    if p['instrument'] == market_id:
      return PerpPosition(size=p['size'], entry_price=p['entry_price'])
  return PerpPosition()


{
  'mainnet': {m: await perp_position(m) for m in MARKETS},
  'testnet': {m: await perp_position(m, on=testnet) for m in (BTC, ETH)},
  'position (defers)': await position(BTC),
}


# %% [markdown]
# ## `leverage`
#
# Fetch the leverage this account can open at on the selected market.
#
# `all_initial_leverage`: the account's initial leverage per instrument (10 by default), with the allowed range and the instrument's margin type. GRVT deprecated setting it (`set_initial_leverage`) in favour of `set_position_config`, which `typed-grvt` does not have; reading it is unaffected.


# %%
async def leverage(market_id: str, /, *, refetch: bool = False, on: Grvt = client) -> Decimal:
  """The account's initial leverage on the market."""
  for row in (await on.trading.all_initial_leverage())['results']:
    if row['instrument'] == market_id:
      return row['leverage']
  raise ValueError(f'No leverage setting for {market_id}')


settings_rows = {
  r['instrument']: r for r in (await client.trading.all_initial_leverage())['results']
}
{
  'mainnet': {m: await leverage(m) for m in MARKETS},
  'testnet': {m: await leverage(m, on=testnet) for m in (BTC, ETH)},
  'ranges': {
    m: (settings_rows[m]['min_leverage'], settings_rows[m]['max_leverage'], settings_rows[m]['margin_type'])
    for m in MARKETS
  },
  'covers every active market': {
    m for m, i in INSTRUMENTS.items() if i.get('status') == 'ACTIVE'
  }
  <= settings_rows.keys(),
}


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
# **Cross** (the exchange, and any market without an isolated position): `account_summary`'s `total_equity`, `initial_margin` and `maintenance_margin`, in USDT; free is equity minus the initial margin (GRVT defines `initial_margin` as the equity required to open positions); leverage is the cross positions' notional over equity. **Isolated** positions carry their own `isolated_balance`, `isolated_im` and `isolated_mm`; no isolated position can be opened through `typed-grvt` (no `set_position_config`; see `typed-client-issues.md`), so that bucket raises `NotImplementedError`. The cross bucket with a position open is checked in the testnet round trip.
#
# Both accounts are in multi-asset mode, where `margin_balance` is `total_equity` times the collateral value ratio (99.8% on testnet's USDT and USDC): shown beside the mapping, undecided which one GRVT checks orders against.


# %%
async def perp_collateral(
  market_id: str | None = None, /, *, on: Grvt = client
) -> PerpCollateral:
  """The cross bucket; isolated buckets are unverified."""
  summary = await on.trading.account_summary()
  if market_id is not None and any(
    p['instrument'] == market_id and p['margin_type'] == 'ISOLATED'
    for p in summary['positions']
  ):
    raise NotImplementedError('Isolated GRVT buckets are not verified')
  equity = summary['total_equity']
  notional = sum(
    (abs(p['notional']) for p in summary['positions'] if p['margin_type'] == 'CROSS'),
    Decimal(0),
  )
  return PerpCollateral(
    equity=equity,
    free_collateral=equity - summary['initial_margin'],
    initial_margin=summary['initial_margin'],
    maintenance_margin=summary['maintenance_margin'],
    leverage=notional / equity if equity > 0 else Decimal(0),
    margin_mode='cross',
  )


async def figures(c: Grvt) -> dict[str, Any]:
  """The account summary's balance figures beside the mapping."""
  s = await c.trading.account_summary()
  return {
    'sub_account_mode': s['sub_account_mode'],
    'total_equity': s['total_equity'],
    'margin_balance': s['margin_balance'],
    'available_balance': s['available_balance'],
    'initial_margin': s['initial_margin'],
    'maintenance_margin': s['maintenance_margin'],
  }


{
  'mainnet': (await perp_collateral(), await collateral(BTC)),
  'testnet': (await perp_collateral(on=testnet), await figures(testnet)),
  'testnet collateral value ratios': [
    (a['currency'], a['collateral_value_ratio'])
    for a in (await testnet.market.collateral_asset_info())['assets']
  ],
}

# %%
# `available_notional`, now that `perp_collateral` and `leverage` are defined, beside BTC's caps.
margin = await client.market.margin_rules(BTC)
{
  'mainnet': {m: await available_notional(m) for m in MARKETS},
  'testnet': {m: await available_notional(m, on=testnet) for m in (BTC, ETH)},
  'BTC caps': (
    margin['max_position_size'],
    [
      (b['notional_floor'], b.get('notional_cap'), b['max_leverage'])
      for b in margin['risk_brackets'][:2]
    ],
  ),
}

# %% [markdown]
# ## Testnet round trip
#
# **Testnet only, user-approved for this verification:** one minimum-size round trip on `BTC_USDT_Perp`, opened and closed by `MARKET` orders (`place_order`'s mapping: the venue's market order, immediate-or-cancel, no limit price), with client order ids in [2^63, 2^64). It shows what the reads above could not on a flat account: a `trades_stream` fill, a non-zero `perp_position`, the cross bucket and `available_notional` with a position, and a filled order's `query_order`. The `place_order` cell is not re-run (it rests post-only orders), so `market_order` repeats its `MARKET` branch.


# %%
def market_new(market_id: str, qty: Decimal, client_order_id: str) -> NewOrder:
  """`place_order`'s `MARKET` branch: the venue's market order, immediate-or-cancel."""
  return {
    'is_market': True,
    'time_in_force': 'IMMEDIATE_OR_CANCEL',
    'metadata': {'client_order_id': client_order_id},
    'legs': [{'instrument': market_id, 'size': abs(qty), 'is_buying_asset': qty > 0}],
  }


async def market_order(market_id: str, qty: Decimal, client_order_id: str) -> GrvtOrder:
  """Send one market order, on testnet only."""
  require_testnet(testnet)
  return await testnet.trading.create_order(market_new(market_id, qty, client_order_id))


def min_qty(market_id: str, price: Decimal, notional: Decimal = Decimal(0)) -> Decimal:
  """The fewest size steps whose notional at `price` clears `min_notional` and `notional`."""
  i = TESTNET_INSTRUMENTS[market_id]
  floor = max(i['min_notional'], notional)
  steps = (floor / price / i['min_size']).to_integral_value(ROUND_UP)
  return max(steps, Decimal(1)) * i['min_size']


def status_of(o: GrvtOrder | None) -> str | None:
  """An order's status, if it carries a state."""
  state = o.get('state') if o is not None else None
  return state['status'] if state is not None else None


if (await perp_position(BTC, on=testnet)).size:
  raise RuntimeError('The testnet account already holds BTC; the round trip needs it flat')
btc_ask = (await testnet.market.ticker(BTC)).get('best_ask_price')
if not btc_ask:
  raise RuntimeError('No testnet ask on BTC')
round_qty = min_qty(BTC, btc_ask)
open_id, close_id = random_client_order_id(), random_client_order_id()
round_start = datetime.now(timezone.utc)
streamed: list[Trade] = []
closed: GrvtOrder | None = None

async with trades_stream(BTC, on=testnet) as own_fills:

  async def collect():
    """Keep every streamed fill."""
    async for t in own_fills:
      streamed.append(t)

  collector = asyncio.create_task(collect())
  await asyncio.sleep(1)
  opened = await market_order(BTC, round_qty, open_id)
  await asyncio.sleep(3)
  held = await perp_position(BTC, on=testnet)
  held_collateral = await perp_collateral(BTC, on=testnet)
  held_notional = await available_notional(BTC, on=testnet)
  if held.size:
    closed = await market_order(BTC, -held.size, close_id)
  await asyncio.sleep(3)
  collector.cancel()
  await asyncio.gather(collector, return_exceptions=True)
round_end = datetime.now(timezone.utc)
{
  'qty': round_qty,
  'replies (own id, order_id, status)': [
    (o['metadata']['client_order_id'] in (open_id, close_id), o.get('order_id'), status_of(o))
    for o in (opened, closed)
    if o is not None
  ],
  'held': held,
  'held collateral': held_collateral,
  'held available_notional': held_notional,
  'streamed': [brief(t) for t in streamed],
}

# %%
# Read the round trip back, read-only and re-runnable: the newest two BTC fills of API-placed
# orders (client order ids in [2^63, 2^64)), their orders, the fees. History trails the stream
# by a few seconds: read right after the cell above, it held only the opening fill.
day_ago = datetime.now(timezone.utc) - timedelta(days=1)
round_fills = [
  t
  async for page in trades_history(BTC, day_ago, datetime.now(timezone.utc), on=testnet)
  for t in page
  if t.client_order_id and int(t.client_order_id) >= 2**63
][:2]
round_states = [
  await query_order(BTC, t.client_order_id, on=testnet)
  for t in round_fills
  if t.client_order_id
]
round_taker = (await fees(BTC, on=testnet)).taker_buy
{
  'history': [brief(t) for t in round_fills],
  'order_id == client_order_id': all(t.order_id == t.client_order_id for t in round_fills),
  'query (qty, filled, active, status)': [
    (s.qty, s.filled_qty, s.active, s.details['state']['status'])
    for s in round_states
    if s is not None
  ],
  'fee vs notional x taker': [
    (t.fee.amount if t.fee else None, abs(t.qty) * t.price * round_taker)
    for t in round_fills
  ],
  'flat after': await perp_position(BTC, on=testnet),
  'open orders left': len(await testnet.trading.open_orders()),
}

# %% [markdown]
# ## Testnet funding position
#
# **Testnet only, user-approved:** a tiny position (about 25 USDT) on a 4-hour perpetual, held across its next settlement to produce a funding payment, then closed by the cell after it. The approval was for an isolated position, to verify the isolated bucket as well; `typed-grvt` cannot set a margin type (`set_position_config`, see `typed-client-issues.md`) and every testnet instrument is cross for this account, so the position is cross and the isolated bucket stays unverified. The side is the one the indicative rate pays (short when it is positive), so the payment should come out positive in the SDK's received-positive sign.

# %%
# The round trip's order helpers again: its cell trades and must not run a second time, so
# the funding cells below take them from here.
def market_new(market_id: str, qty: Decimal, client_order_id: str) -> NewOrder:
  """`place_order`'s `MARKET` branch: the venue's market order, immediate-or-cancel."""
  return {
    'is_market': True,
    'time_in_force': 'IMMEDIATE_OR_CANCEL',
    'metadata': {'client_order_id': client_order_id},
    'legs': [{'instrument': market_id, 'size': abs(qty), 'is_buying_asset': qty > 0}],
  }


async def market_order(market_id: str, qty: Decimal, client_order_id: str) -> GrvtOrder:
  """Send one market order, on testnet only."""
  require_testnet(testnet)
  return await testnet.trading.create_order(market_new(market_id, qty, client_order_id))


def min_qty(market_id: str, price: Decimal, notional: Decimal = Decimal(0)) -> Decimal:
  """The fewest size steps whose notional at `price` clears `min_notional` and `notional`."""
  i = TESTNET_INSTRUMENTS[market_id]
  floor = max(i['min_notional'], notional)
  steps = (floor / price / i['min_size']).to_integral_value(ROUND_UP)
  return max(steps, Decimal(1)) * i['min_size']


def status_of(o: GrvtOrder | None) -> str | None:
  """An order's status, if it carries a state."""
  state = o.get('state') if o is not None else None
  return state['status'] if state is not None else None


# %%
FUNDING_NOTIONAL = Decimal(25)
"""Notional of the funding position, in USDT."""


def tight(t: GrvtTicker) -> bool:
  """Both sides quoted, within 0.3% of each other."""
  bid, ask = t.get('best_bid_price'), t.get('best_ask_price')
  return bool(bid and ask and (ask - bid) / ask < Decimal('0.003'))


four_hour = [
  n
  for n, i in TESTNET_INSTRUMENTS.items()
  if i.get('funding_interval_hours') == 4 and i.get('status') == 'ACTIVE' and n in INSTRUMENTS
]
quotes = dict(
  zip(
    four_hour,
    await asyncio.gather(*(testnet.market.ticker(n, transport='ws') for n in four_hour)),
  )
)
funding_market = max(
  (n for n, t in quotes.items() if tight(t) and t.get('funding_rate')),
  key=lambda n: abs(quotes[n].get('funding_rate') or Decimal(0)),
)
funding_quote = quotes[funding_market]
indicative = funding_quote.get('funding_rate') or Decimal(0)
side = Decimal(-1) if indicative > 0 else Decimal(1)
entry = funding_quote.get('best_ask_price' if side > 0 else 'best_bid_price')
if not entry:
  raise RuntimeError(f'No testnet quote on {funding_market}')
if any(p['size'] for p in await testnet.trading.positions(kind=['PERPETUAL'])):
  raise RuntimeError('The testnet account holds a position; the funding check needs it flat')
funding_qty = side * min_qty(funding_market, entry, FUNDING_NOTIONAL)
funding_opened = await market_order(funding_market, funding_qty, random_client_order_id())
await asyncio.sleep(3)
{
  'market': funding_market,
  'interval hours': TESTNET_INSTRUMENTS[funding_market].get('funding_interval_hours'),
  'next funding': funding_quote.get('next_funding_time'),
  'indicative %': indicative,
  'qty': funding_qty,
  'status': status_of(funding_opened),
  'position': await perp_position(funding_market, on=testnet),
}

# %%
# After the settlement: the payment by market and exchange-wide, beside the venue's rows and
# the settled rate, then the position is closed. Self-contained: it finds the open position.
held_rows = [p for p in await testnet.trading.positions(kind=['PERPETUAL']) if p['size']]
if len(held_rows) != 1:
  raise RuntimeError('Expected exactly the funding position open on testnet')
held_row = held_rows[0]
held_market = held_row['instrument']
since = datetime.now(timezone.utc) - timedelta(hours=5)
now = datetime.now(timezone.utc)
settlements = (
  await testnet.market.funding_rate(instrument=held_market, start_time=since, end_time=now)
)['result']
venue_rows = (
  await testnet.trading.funding_payment_history(
    instrument=held_market, start_time=since, end_time=now
  )
)['result']
by_market = [
  p async for page in funding_payments(held_market, since, now, on=testnet) for p in page
]
exchange_wide = [
  p async for page in funding_payments(None, since, now, on=testnet) for p in page
]
held_size, held_entry = held_row['size'], held_row['entry_price']
# The close is signed for 29 days, the implementation's `ORDER_TTL`, to check the venue
# accepts a signature that far ahead (it caps them at 30 days).
close_order: NewOrder = {
  'is_market': True,
  'time_in_force': 'IMMEDIATE_OR_CANCEL',
  'signature': {'expiration': datetime.now(timezone.utc) + timedelta(days=29)},
  'metadata': {'client_order_id': random_client_order_id()},
  'legs': [
    {'instrument': held_market, 'size': abs(held_size), 'is_buying_asset': held_size < 0}
  ],
}
require_testnet(testnet)
funding_closed = await testnet.trading.create_order(close_order)
await asyncio.sleep(3)
{
  'market': held_market,
  'size, entry': (held_size, held_entry),
  'settled (time, rate %)': [(r['funding_time'], r['funding_rate']) for r in settlements],
  'venue rows (time, amount, currency)': [
    (r['event_time'], r['amount'], r['currency']) for r in venue_rows
  ],
  'cumulative_realized_funding_payment': held_row['cumulative_realized_funding_payment'],
  'payments': by_market,
  'exchange-wide': exchange_wide,
  'expected received (time, -size x mark x rate)': [
    (r['funding_time'], -held_size * r['mark_price'] * r['funding_rate'] / PERCENT)
    for r in settlements
  ],
  'close status, signature expiry': (
    status_of(funding_closed),
    funding_closed['signature']['expiration'],
  ),
  'close state': (await testnet.trading.order(
    {'client_order_id': funding_closed['metadata']['client_order_id']}
  )).get('state'),
  'flat after': await perp_position(held_market, on=testnet),
}

# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`. "Testnet" marks cells executed against testnet; every other read ran on mainnet.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | `all_instruments(kinds=['PERPETUAL'])`: 194 mainnet perps (184 active, 10 delisted), all USDT-quoted, one per base/quote. |
# | `depth` | verified | `orderbook` at depth 10/50/100/500; 500 covers whole books (BTC < 500 levels per side). `time` is `event_time`. |
# | `depth_stream` | verified | `v1.book.d` at 50 ms: snapshot, then deltas; the client enforces sequence continuity. |
# | `tickers` | verified | One `ticker` per market over WS, concurrently (no bulk endpoint). `0` prices of empty sides map to `None`. 24h volume is taker buy + sell, matching the sum of 1440 one-minute candles. |
# | `rules` | verified | Instrument `tick_size`, `min_size` (also the step: `2065` off it), `min_notional`; `fee_asset` USDT; `fees` the published tier-1 schedule (static, read 2026-10-22). |
# | `fees` | verified | `funding_account_summary` tier: futures maker/taker in millionths (tier 1: -1/450). Unit fixed by the published schedule and testnet taker fills (`fee_rate` 0.045%, `fee` = notional x 0.00045). Maker side seen only as the tier figure. |
# | `candles` | verified | `candlesticks_paged` (TRADE), six intervals; venue bounds inclusive, exclusive end applied locally; 2500-row walk without gaps or duplicates. |
# | `query_order` | verified | Testnet: by client order id; `1004` maps to `None`; cancelled and filled orders stay queryable (`CANCELLED`/`CLIENT_CANCEL`; `FILLED` with signed traded size, round trip). |
# | `open_orders` | verified | Testnet: base/quote-scoped `open_orders`; live orders listed and gone after cancels. Mainnet empty. |
# | `trades_history` | verified | Testnet fills (mainnet account has none): per market and exchange-wide, venue-applied bounds, cursor pages of 2 equal one walk. Fee in `fee_currency`. |
# | `trades_stream` | verified | Testnet round trip: both IOC fills streamed with trade id, client order id, signed size, taker role and USDT fee, identical to the history rows; history trails the stream by a few seconds. Mainnet subscribes, no fills. |
# | `position` | verified | Defers to `perp_position` (testnet positions held, see below). |
# | `available_notional` | verified | Default: cross free collateral x `leverage` (testnet 20019 x 10; 20002.93 x 10 with 0.002 BTC held). Venue caps (`max_position_size`, risk brackets) not applied. |
# | `place_order` | verified | Testnet: POST_ONLY placed (`PENDING`, `0x00` reply, `OPEN` on lookup); MARKET (round trip: IOC, no price, `PENDING` reply, `FILLED` on lookup); off-tick (`2064`) and off-step (`2065`) refused as `BadRequest`. LIMIT branch (GTT without `post_only`) not sent. |
# | `cancel_order` | verified | Testnet: by client order id; `CANCELLED`/`CLIENT_CANCEL`. The venue acks unknown ids too. |
# | `cancel_orders` | verified | Testnet: `bulk_orders` by `client_order_i_ds`; both cancelled. |
# | `cancel_open_orders` | verified | Testnet: `cancel_all_orders` scoped by kind/base/quote; BTC orders cancelled, the ETH order survived. Nothing left open. |
# | `index` | verified | `mini_ticker` `index_price`. |
# | `next_funding` | verified | Ticker `funding_rate` (percent, not the documented centibeeps) and `next_funding_time`; interval from the instrument (8 h or 4 h). No premium. |
# | `perp_stats` | verified | Concurrent tickers: index, mark, indicative funding, base-unit open interest. |
# | `funding_rates` | verified | `funding_rate_paged`, percent, inclusive bounds. BTC rows up to 2025-10-15 08:00 UTC are per-minute with interval `0`, not settlements (needs a decision). |
# | `funding_payments` | verified | Testnet funding position (234 BARD long, cross, across the 2026-10-22 12:00 UTC settlement at -0.0241%): venue `amount` -0.006097 (received), SDK +0.006097, equal to -size x mark x rate and to the position's `cumulative_realized_funding_payment`; per market and exchange-wide. Mainnet none. |
# | `perp_position` | verified | Testnet: +0.002 BTC at 81835.0 while held, flat after the close; +234 BARD at 0.1072 (funding position). Mainnet flat. |
# | `leverage` | verified | `all_initial_leverage` per instrument (10 default; covers every active market). |
# | `collateral` | verified | Defers to `perp_collateral`. |
# | `perp_collateral` | verified | Cross bucket from `account_summary` (testnet equity 20019, mainnet zeros; with 0.002 BTC held: initial 16.37, maintenance 1.64, leverage 0.0082). Isolated bucket blocked: `set_position_config` is missing from `typed-grvt`, so it raises `NotImplementedError`; multi-asset `margin_balance` vs `total_equity` undecided. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets=set(listed), assets={'USDT'})
missing = gap('grvt', ids, load_catalogue())
(missing.assets, len(missing.perp_markets), missing.perp_markets)

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
