# %% [markdown]
# # kucoin `market` PoC
#
# Maps `typed_kucoin` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
)

from typed_kucoin import KuCoin

from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  FundingRate,
  Collateral,
  Fees,
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

stack = AsyncExitStack()
client = await stack.enter_async_context(KuCoin.new(public=True))

MARKETS = ['spot:BTC-USDT', 'spot:ETH-USDT', 'perp:XBTUSDTM', 'perp:ETHUSDTM']

end = datetime.now(timezone.utc)
start = end - timedelta(days=7)

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_kucoin',
    'KuCoin',
    grep=r'^(spot|futures)\.(all_symbols|symbol|all_tickers|ticker|klines|part_orderbook|funding_fees\.(current_funding_rate|public_funding_history))|streams\.(spot_margin_public|futures_public)\.orderbook_level',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """List active spot pairs and linear perpetual contracts with native IDs."""
  spot = await client.spot.all_symbols()
  perp = await client.futures.all_symbols()
  return [f'spot:{s["symbol"]}' for s in spot if s['enableTrading']] + [
    f':{s["symbol"]}'
    for s in perp
    if s['status'] == 'Open'
    and s['expireDate'] is None
    and not s['isInverse']
    and s['settleCurrency'] == s['quoteCurrency']
    and s['multiplier'] > 0
  ]


listed = await markets()
(len(listed), [m for m in MARKETS if m in listed])


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.


# %%
async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Convert linear contract lots into base quantities."""
  exchange, symbol = market_id.split(':', 1)
  size = '100' if levels and levels > 20 else '20'
  if exchange == 'spot':
    raw = await client.spot.part_orderbook(size, symbol=symbol)
    book = Book(
      bids=[Book.Entry(p, q) for p, q in raw['bids']],
      asks=[Book.Entry(p, q) for p, q in raw['asks']],
    )
  else:
    contract = await client.futures.symbol(symbol)
    multiplier = Decimal(str(contract['multiplier']))
    raw_perp = await client.futures.part_orderbook(size, symbol=symbol)
    book = Book(
      bids=[
        Book.Entry(Decimal(str(p)), Decimal(q) * multiplier)
        for p, q in raw_perp['bids']
      ],
      asks=[
        Book.Entry(Decimal(str(p)), Decimal(q) * multiplier)
        for p, q in raw_perp['asks']
      ],
    )
  return book.limit(levels) if levels is not None else book


{market_id: await depth(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.


# %%
@asynccontextmanager
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Probe public five-level snapshot streams and native quantity units."""
  exchange, symbol = market_id.split(':', 1)
  if exchange == 'spot':
    source = client.streams.spot_margin_public.orderbook_level5(symbol)
    async with source as stream:

      async def spot_books():
        """Map public spot snapshots."""
        async for row in stream:
          yield Book(
            bids=[Book.Entry(p, q) for p, q in row['bids']],
            asks=[Book.Entry(p, q) for p, q in row['asks']],
          )

      yield spot_books()
  else:
    contract = await client.futures.symbol(symbol)
    multiplier = Decimal(str(contract['multiplier']))
    async with client.streams.futures_public.orderbook_level5(symbol) as stream_:

      async def perp_books():
        """Map linear perpetual snapshots to base units."""
        async for row in stream_:
          yield Book(
            bids=[Book.Entry(p, Decimal(q) * multiplier) for p, q in row['bids']],
            asks=[Book.Entry(p, Decimal(q) * multiplier) for p, q in row['asks']],
          )

      yield perp_books()


async def first_book(market_id: str):
  """Bound the live stream probe to one update."""
  async with depth_stream(market_id) as stream:
    return await asyncio.wait_for(anext(aiter(stream)), timeout=20)


{market_id: await first_book(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.


# %%
async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Map native ticker prices and sizes without depth-derived prices."""
  spot = await client.spot.all_tickers()
  contracts = {
    c['symbol']: c
    for c in await client.futures.all_symbols()
    if not c['isInverse']
    and c['expireDate'] is None
    and c['settleCurrency'] == c['quoteCurrency']
    and c['multiplier'] > 0
  }
  perp = await client.futures.all_tickers()
  result = {
    f'spot:{r["symbol"]}': Ticker(
      last=r['last'],
      bid=r['buy'],
      ask=r['sell'],
      bid_qty=r['bestBidSize'],
      ask_qty=r['bestAskSize'],
      base_volume_24h=r['vol'],
    )
    for r in spot['ticker']
  }
  for r in perp:
    if r['symbol'] in contracts:
      c = contracts[r['symbol']]
      multiplier = Decimal(str(c['multiplier']))
      result[f':{r["symbol"]}'] = Ticker(
        last=r['price'],
        bid=r['bestBidPrice'],
        ask=r['bestAskPrice'],
        bid_qty=Decimal(r['bestBidSize']) * multiplier,
        ask_qty=Decimal(r['bestAskSize']) * multiplier,
        base_volume_24h=Decimal(str(c['volumeOf24h'])),
      )
  return {k: v for k, v in result.items() if markets is None or k in markets}


await tickers(MARKETS)


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Read public constraints without account fees."""
  exchange, symbol = market_id.split(':', 1)
  if exchange == 'spot':
    s = await client.spot.symbol(symbol)
    return Rules(
      fee_asset=s['feeCurrency'],
      tick_size=s['priceIncrement'],
      step_size=s['baseIncrement'],
      fixed_min_qty=s['baseMinSize'],
      max_qty=s['baseMaxSize'],
      min_value=s['minFunds'],
      api=s['enableTrading'],
      details=s,
    )
  c = await client.futures.symbol(symbol)
  multiplier = Decimal(str(c['multiplier']))
  return Rules(
    fee_asset=c['settleCurrency'],
    tick_size=Decimal(str(c['tickSize'])),
    step_size=Decimal(c['lotSize']) * multiplier,
    fixed_min_qty=Decimal(c['lotSize']) * multiplier,
    max_qty=Decimal(c['maxOrderQty']) * multiplier,
    api=c['status'] == 'Open',
    details=c,
  )


{market_id: (await rules(market_id)).step_size for market_id in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.

# %%
from tribulnation.sdk.market.types.candles import candle_windows
from typing_extensions import Literal

SpotInterval = Literal['1min', '5min', '15min', '1hour', '4hour', '1day']
PerpInterval = Literal[1, 5, 15, 60, 240, 1440]
SPOT_INTERVALS: dict[CandleInterval, SpotInterval] = {
  '1m': '1min',
  '5m': '5min',
  '15m': '15min',
  '1h': '1hour',
  '4h': '4hour',
  '1d': '1day',
}
PERP_INTERVALS: dict[CandleInterval, PerpInterval] = {
  '1m': 1,
  '5m': 5,
  '15m': 15,
  '1h': 60,
  '4h': 240,
  '1d': 1440,
}


def inclusive_end(end: datetime, *, precision: timedelta) -> datetime:
  """Last representable wire timestamp below the SDK exclusive bound."""
  tick = end.replace(microsecond=0)
  if precision < timedelta(seconds=1):
    tick = end.replace(microsecond=end.microsecond // 1000 * 1000)
  return tick - precision if tick == end else tick


async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Page fixed time windows, preserving sparse periods and half-open bounds."""
  exchange, symbol = market_id.split(':', 1)
  if exchange == 'spot':
    for lower, upper in candle_windows(start, end, interval, size=1500):
      rows = await client.spot.klines(
        symbol,
        type=SPOT_INTERVALS[interval],
        start_at=lower,
        end_at=inclusive_end(upper, precision=timedelta(seconds=1)),
      )
      yield [
        Candle(time=t, open=o, close=c, high=h, low=l, volume=v, quote_volume=q)
        for t, o, c, h, l, v, q in rows
        if lower <= t < upper
      ]
  else:
    contract = await client.futures.symbol(symbol)
    multiplier = Decimal(str(contract['multiplier']))
    for lower, upper in candle_windows(start, end, interval, size=200):
      rows_perp = await client.futures.klines(
        symbol,
        granularity=PERP_INTERVALS[interval],
        from_=lower,
        to=inclusive_end(upper, precision=timedelta(milliseconds=1)),
      )
      yield [
        Candle(
          time=t,
          open=Decimal(str(o)),
          high=Decimal(str(h)),
          low=Decimal(str(l)),
          close=Decimal(str(c)),
          volume=Decimal(str(v)) * multiplier,
          quote_volume=Decimal(str(q)),
        )
        for t, o, h, l, c, v, q in rows_perp
        if lower <= t < upper
      ]


{
  market_id: [
    len(page) async for page in candles(market_id, '1m', end - timedelta(hours=26), end)
  ]
  for market_id in MARKETS
}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.


# %%
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
async def trades_history(market_id: str, /, start: datetime, end: datetime):
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.


# %%
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def position(market_id: str, /) -> Position:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
async def available_notional(market_id: str, /):
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `place_order`
#
# Place an order in the market.


# %%
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}):
  """Read the published contract index price."""
  return Decimal(
    str((await client.futures.symbol(market_id.split(':', 1)[1]))['indexPrice'])
  )


{
  market_id: await index(market_id)
  for market_id in MARKETS
  if market_id.startswith('perp:')
}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.


# %%
async def next_funding(market_id: str, /) -> NextFunding:
  """Use the dedicated public current funding endpoint's settlement timestamp."""
  row = await client.futures.funding_fees.current_funding_rate(
    market_id.split(':', 1)[1]
  )
  return NextFunding(
    rate=Decimal(str(row['value'])),
    time=row['fundingTime'],
    interval=timedelta(milliseconds=row['granularity']),
  )


{
  market_id: await next_funding(market_id)
  for market_id in MARKETS
  if market_id.startswith('perp:')
}


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Map published prices and open interest; funding comes from its dedicated endpoint."""
  rows = await client.futures.all_symbols()
  result: dict[str, PerpStats] = {}
  for c in rows:
    key = f':{c["symbol"]}'
    if (
      c['expireDate'] is not None
      or c['isInverse']
      or c['settleCurrency'] != c['quoteCurrency']
      or c['multiplier'] <= 0
    ):
      continue
    if markets is not None and key not in markets:
      continue
    result[key] = PerpStats(
      index=Decimal(str(c['indexPrice'])),
      mark=Decimal(str(c['markPrice'])),
      open_interest=Decimal(c['openInterest']) * Decimal(str(c['multiplier'])),
    )
  return result


await perp_stats(MARKETS)


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Walk settled funding backwards; an open lower bound means earliest available."""
  symbol = market_id.split(':', 1)[1]
  lower = start or datetime(1970, 1, 1, tzinfo=timezone.utc)
  upper = end or datetime.now(timezone.utc)
  async for page in client.futures.funding_fees.public_funding_history_paged(
    symbol, from_=lower, to=upper
  ):
    yield [
      FundingRate(time=r['timepoint'], rate=Decimal(str(r['fundingRate'])))
      for r in page
      if lower <= r['timepoint'] <= upper
    ]


{
  market_id: [
    len(page) async for page in funding_rates(market_id, end - timedelta(days=40), end)
  ]
  for market_id in MARKETS
  if market_id.startswith('perp:')
}


# %% [markdown]
# ## `funding_payments`
#
# Fetch your funding payments history.


# %%
async def funding_payments(market_id: str, /, start: datetime, end: datetime):
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.


# %%
async def perp_position(market_id: str, /) -> PerpPosition:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.


# %%
async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  """Outside this public-data qualification."""
  raise NotImplementedError('Private trading/account data or unqualified public method')


# not executed: outside the public-data qualification

# %% [markdown]
# ## Coverage
#
# REST depth is capped at 100; the qualified WebSocket feed is five levels.
# Futures candles returned at most 200 rows despite Classic docs claiming 500.
# Candle gaps remain native gaps; historical probes are not an archive guarantee.
# Perpetual exchange ID is perp; existing Catalogue rows need explicit exchange metadata.
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, numbered in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `depth` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `depth_stream` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `tickers` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `rules` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `fees` | not attempted | Outside public-data scope. |
# | `candles` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `query_order` | not attempted | Outside public-data scope. |
# | `open_orders` | not attempted | Outside public-data scope. |
# | `trades_history` | not attempted | Outside public-data scope. |
# | `trades_stream` | not attempted | Outside public-data scope. |
# | `position` | not attempted | Outside public-data scope. |
# | `available_notional` | not attempted | Outside public-data scope. |
# | `place_order` | not attempted | Outside public-data scope. |
# | `cancel_order` | not attempted | Outside public-data scope. |
# | `cancel_orders` | not attempted | Outside public-data scope. |
# | `cancel_open_orders` | not attempted | Outside public-data scope. |
# | `index` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `next_funding` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `perp_stats` | verified | Native index, mark and base-unit open interest; funding via next_funding. |
# | `funding_rates` | verified | Credential-free Classic public read on BTC and ETH, 2026-09-18. |
# | `funding_payments` | not attempted | Outside public-data scope. |
# | `perp_position` | not attempted | Outside public-data scope. |
# | `collateral` | not attempted | Outside public-data scope. |
# | `perp_collateral` | not attempted | Outside public-data scope. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue
from sdk_dev.repo import repo_root

listed = await markets()
ids = Ids(
  spot_markets={m for m in listed if m.startswith('spot:')},
  perp_markets={m for m in listed if m.startswith('perp:')},
)
catalogue_gap = gap('kucoin', ids, load_catalogue(root=repo_root()))
{
  'spot_missing': len(catalogue_gap.spot_markets),
  'perp_missing': len(catalogue_gap.perp_markets),
  'spot_sample': catalogue_gap.spot_markets[:10],
  'perp_sample': catalogue_gap.perp_markets[:10],
}


# %% [markdown]
# ## Interval, boundary and retention qualification
#
# Separate successful reads from historical completeness. Old empty windows are
# unavailable data, not proof of no trades or a full archive.

# %%
from tribulnation.sdk.market.types.candles import CANDLE_WIDTHS


async def candle_checks() -> dict[
  tuple[str, CandleInterval], dict[str, list[int] | int]
]:
  """Check all SDK intervals, unique opens and exact page-boundary continuity."""
  result: dict[tuple[str, CandleInterval], dict[str, list[int] | int]] = {}
  for market_id in MARKETS:
    for interval, width in CANDLE_WIDTHS.items():
      upper = end.replace(hour=0, minute=0, second=0, microsecond=0)
      count = 1502 if market_id.startswith('spot:') else 402
      lower = upper - width * count
      pages = [page async for page in candles(market_id, interval, lower, upper)]
      rows = [r for page in pages for r in page]
      times = sorted(r.time for r in rows)
      assert len(times) == len(set(times))
      assert all(lower <= t < upper for t in times)
      assert all(
        r.low <= min(r.open, r.close) <= max(r.open, r.close) <= r.high for r in rows
      )
      result[(market_id, interval)] = {
        'pages': list(map(len, pages)),
        'gaps': sum(b - a != width for a, b in zip(times, times[1:])),
      }
  return result


await candle_checks()


# %%
async def retention_checks() -> dict[tuple[str, int, CandleInterval], list[str]]:
  """Probe fixed historical windows, without extrapolating archive guarantees."""
  result: dict[tuple[str, int, CandleInterval], list[str]] = {}
  for market_id in ['spot:BTC-USDT', 'perp:XBTUSDTM']:
    for year in [2020, 2024, 2025]:
      lower = datetime(year, 1, 2, tzinfo=timezone.utc)
      intervals: tuple[CandleInterval, ...] = ('1m', '1d')
      for interval in intervals:
        width = CANDLE_WIDTHS[interval]
        rows = [
          r
          async for page in candles(market_id, interval, lower, lower + width * 3)
          for r in page
        ]
        result[(market_id, year, interval)] = [r.time.isoformat() for r in rows]
  return result


await retention_checks()


# %%
async def funding_earliest() -> dict[str, int | datetime]:
  """Exercise the open-start contract and detect duplicates across funding pages."""
  pages = [p async for p in funding_rates('perp:XBTUSDTM', end=end)]
  rows = [r for p in pages for r in p]
  assert len(rows) == len({r.time for r in rows})
  return {
    'pages': len(pages),
    'rows': len(rows),
    'earliest': min(r.time for r in rows),
    'latest': max(r.time for r in rows),
  }


await funding_earliest()

# %% [markdown]
# ## Large depth and sparse candle checks

# %%
{market_id: len((await depth(market_id, levels=100)).bids) for market_id in MARKETS}


# %%
async def sparse_checks() -> dict[str, list[str]]:
  """Compare two-minute subwindows with a sparse 200-minute parent window."""
  result: dict[str, list[str]] = {}
  upper = end.replace(hour=0, minute=0, second=0, microsecond=0)
  lower = upper - timedelta(minutes=200)
  for market_id in ['perp:XBTUSDTM', 'perp:ETHUSDTM']:
    rows = [r async for p in candles(market_id, '1m', lower, upper) for r in p]
    times = {r.time for r in rows}
    missing = [
      lower + timedelta(minutes=i)
      for i in range(200)
      if lower + timedelta(minutes=i) not in times
    ]
    recovered: list[str] = []
    for t in missing[:5]:
      probe = [
        r
        async for p in candles(market_id, '1m', t, t + timedelta(minutes=1))
        for r in p
      ]
      recovered.extend(r.time.isoformat() for r in probe)
    result[market_id] = recovered
  return result


await sparse_checks()

# %%
await stack.aclose()
