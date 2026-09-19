# %% [markdown]
# # kraken `market` PoC
#
# Maps `typed_kraken` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
  TypeGuard,
)
from importlib.metadata import version
import asyncio

from tribulnation.kraken import KrakenMarket
from typed_kraken.schemas import FuturesTicker, FuturesMarketTicker
from typed_kraken.futures.instruments import FuturesInstrument
from tribulnation.kraken.core import Calls
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Fees,
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
  candle_width,
)
from tribulnation.sdk.market.types.candles import candle_windows
from tribulnation.sdk.market.exchange import OverflowPolicy

stack = AsyncExitStack()
venue = await stack.enter_async_context(KrakenMarket.new(public=True))
exchange = await venue.exchange('perp')
client = venue.shared.client
calls = venue.shared
MARKETS = ['PF_XBTUSD', 'PF_ETHUSD', 'PF_BONKUSD']
end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
start = end - timedelta(hours=3)
instruments: dict[str, FuturesInstrument] = {}


def is_market(row: FuturesTicker) -> TypeGuard[FuturesMarketTicker]:
  """Distinguish contract tickers from the separate index rows."""
  return 'tag' in row


async def snapshots() -> dict[str, FuturesMarketTicker]:
  """Read validated market tickers, excluding index rows."""
  response = await calls.call_kraken(client.futures.tickers)
  return {r['symbol']: r for r in response['tickers'] if is_market(r)}


version('typed-kraken')

# %% [markdown]
# ## Surface

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_kraken', 'Kraken', grep=r'^futures\.|^charts\.|^spot.market_data.assets$'
  )
)

# %% [markdown]
# ## `markets`


# %%
async def markets() -> Sequence[str]:
  """Exercise the qualified SDK discovery and retain metadata for the observations."""
  global instruments
  instruments = await venue.shared.load_perps()
  return await exchange.markets()


listed = await markets()
assert set(MARKETS) <= set(listed)
{
  'count': len(listed),
  'references': {
    m: {
      k: instruments[m].get(k)
      for k in [
        'type',
        'base',
        'quote',
        'contractSize',
        'contractValueTradePrecision',
        'tickSize',
      ]
    }
    for m in MARKETS
  },
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.


# %%
async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Exercise SDK ordering and trimming with native base quantities."""
  return await (await exchange.market(market_id)).depth(levels=levels)


{m: await depth(m, levels=5) for m in MARKETS}


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
) -> AsyncGenerator[AsyncIterable[Book]]:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.


# %%
async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Exercise SDK bulk snapshot selection."""
  return await exchange.tickers(markets, settings=settings)


{
  'all': len(await tickers()),
  'selected': await tickers(MARKETS),
  'empty': await tickers([]),
}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Exercise SDK precision constraints and native fee-asset resolution."""
  return await (await exchange.market(market_id)).rules(refetch=refetch)


{m: await rules(m) for m in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.


# %%
async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Exercise the implemented SDK page requests and half-open bound filtering."""
  async for page in (await exchange.market(market_id)).candles(interval, start, end):
    yield page


candle_probes = {}
for m in MARKETS[:2]:
  resolutions = await calls.call_kraken(
    lambda: client.charts.resolutions('trade', symbol=m)
  )
  intervals: list[CandleInterval] = ['1m', '5m', '15m', '1h', '4h', '1d']
  for interval in intervals:
    assert interval in resolutions
    width = candle_width(interval)
    rows = [
      r async for page in candles(m, interval, end - 5 * width, end) for r in page
    ]
    candle_probes[(m, interval)] = {
      'rows': len(rows),
      'first': rows[0] if rows else None,
    }
    await asyncio.sleep(0.25)
candle_probes


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def trades_history(market_id: str, /, start: datetime, end: datetime):
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def position(market_id: str, /) -> Position:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def available_notional(market_id: str, /):
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  """Exercise the native index-price SDK mapping."""
  return await exchange.index(market_id, settings=settings)


{m: await index(m) for m in MARKETS}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def next_funding(market_id: str, /) -> NextFunding:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Exercise native public statistics without derived funding estimates."""
  return await exchange.perp_stats(markets, settings=settings)


{'selected': await perp_stats(MARKETS), 'empty': await perp_stats([])}


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.


# %%
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Use the approved native-period-start plus one-hour settlement conversion."""
  async for page in (await exchange.market(market_id)).funding_rates(start, end):
    yield page


funding_probes = {}
for m in MARKETS[:2]:
  rows = [r async for page in funding_rates(m) for r in page]
  bounded = [
    r async for page in funding_rates(m, rows[-3].time, rows[-1].time) for r in page
  ]
  assert len(bounded) == 3
  funding_probes[m] = {'count': len(rows), 'first': rows[0], 'last': rows[-1]}
funding_probes


# %% [markdown]
# ## `funding_payments`
#
# Fetch your funding payments history.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def funding_payments(market_id: str, /, start: datetime, end: datetime):
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def perp_position(market_id: str, /) -> PerpPosition:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.


# %%
# not executed: Public REST qualification excludes private methods, trading, Futures streams and unqualified next funding.
async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  """Outside the qualified public Futures surface."""
  raise NotImplementedError('Outside the qualified public Futures surface')


# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `depth` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `depth_stream` | not supported | No qualified native Futures stream or next-funding mapping. |
# | `tickers` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `rules` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `fees` | not attempted | Private Futures methods and trading are outside scope. |
# | `candles` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `query_order` | not attempted | Private Futures methods and trading are outside scope. |
# | `open_orders` | not attempted | Private Futures methods and trading are outside scope. |
# | `trades_history` | not attempted | Private Futures methods and trading are outside scope. |
# | `trades_stream` | not attempted | Private Futures methods and trading are outside scope. |
# | `position` | not attempted | Private Futures methods and trading are outside scope. |
# | `available_notional` | not attempted | Private Futures methods and trading are outside scope. |
# | `place_order` | not attempted | Private Futures methods and trading are outside scope. |
# | `cancel_order` | not attempted | Private Futures methods and trading are outside scope. |
# | `cancel_orders` | not attempted | Private Futures methods and trading are outside scope. |
# | `cancel_open_orders` | not attempted | Private Futures methods and trading are outside scope. |
# | `index` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `next_funding` | not supported | No qualified native Futures stream or next-funding mapping. |
# | `perp_stats` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `funding_rates` | verified | Released typed-kraken 0.4.0 and actual SDK methods executed live. |
# | `funding_payments` | not attempted | Private Futures methods and trading are outside scope. |
# | `perp_position` | not attempted | Private Futures methods and trading are outside scope. |
# | `collateral` | not attempted | Private Futures methods and trading are outside scope. |
# | `perp_collateral` | not attempted | Private Futures methods and trading are outside scope. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
ids = Ids(perp_markets={f'perp:{m}' for m in listed}, assets={'ZUSD'})
from sdk_dev.repo import repo_root

gap('kraken', ids, load_catalogue(root=repo_root()))


# %% [markdown]
# ## Candle boundary, paging and retention probes

# %%
cross_page = {}
for m in MARKETS[:2]:
  close = end.replace(minute=0)
  lower = close - timedelta(hours=2050)
  pages = [page async for page in candles(m, '1h', lower, close)]
  times = [r.time for page in pages for r in page]
  assert len(times) == len(set(times)) == 2050
  cross_page[m] = {
    'pages': [len(page) for page in pages],
    'first': times[0],
    'last': times[-1],
  }

edge = end.replace(minute=0) - timedelta(hours=4)
boundary_probes = {}
for name, lower, upper in [
  ('fractional', edge + timedelta(microseconds=1), edge + timedelta(hours=2)),
  ('forming', end, end + timedelta(minutes=1)),
  ('empty', edge, edge),
  (
    'prelisting',
    datetime(2020, 1, 1, tzinfo=timezone.utc),
    datetime(2020, 1, 2, tzinfo=timezone.utc),
  ),
  (
    '2023',
    datetime(2023, 1, 1, tzinfo=timezone.utc),
    datetime(2023, 1, 3, tzinfo=timezone.utc),
  ),
]:
  rows = [
    r
    async for page in candles(
      'PF_XBTUSD', '1h' if name != 'forming' else '1m', lower, upper
    )
    for r in page
  ]
  assert all(lower <= r.time < upper for r in rows)
  boundary_probes[name] = {'count': len(rows), 'first': rows[0].time if rows else None}
{'cross_page': cross_page, 'bounds': boundary_probes}

# %% [markdown]
# ## Cleanup

# %%
await stack.aclose()
