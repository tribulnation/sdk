# %% [markdown]
# # Kraken public Market qualification
#
# SDK #33: re-run the existing Spot mappings through the validated typed client.
# Private methods are outside this probe. Futures is qualified separately in `futures.py`;
# see `typed-client-issues.md` and `dev-docs/kraken-public-market.md`.

# %%
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.metadata import version
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
)

from tribulnation.sdk import Context, NetworkError, RateLimited
from tribulnation.kraken import KrakenMarket
from tribulnation.kraken.market.impl.candles import INTERVALS
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Fees,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Ticker,
  Trade,
  candle_width,
)
from tribulnation.sdk.market.exchange import OverflowPolicy

stack = AsyncExitStack()
venue = await stack.enter_async_context(KrakenMarket.new(public=True))
exchange = await venue.exchange('spot')
client = venue.shared.client
MARKETS = ['XBTUSD', 'ETHUSD']
end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
start = end - timedelta(minutes=5)
{
  package: version(package)
  for package in ['typed-kraken', 'tribulnation-sdk', 'tribulnation-kraken']
}

# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_kraken',
    'Kraken',
    grep=r'^spot.market_data.(asset_pairs|depth|ticker|ohlc)$|^streams.market_data.book$',
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """Join the internal/display AssetPairs listings through the existing SDK mapping."""
  return await exchange.markets()


listed = await markets()
assert set(MARKETS) <= set(listed)
{
  'count': len(listed),
  'references': {m: (await exchange.market(m)).meta['pair'] for m in MARKETS},
}


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.


# %%
async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Read public Depth through the SDK's typed row mapping."""
  return await (await exchange.market(market_id)).depth(levels=levels)


{(m, n): len((await depth(m, levels=n)).bids) for m in MARKETS for n in [5, 100]}


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
  """Fold validated book snapshots and updates through the existing SDK mapping."""
  market = await exchange.market(market_id)
  async with market.depth_stream(
    levels=levels, queue_size=queue_size, overflow=overflow
  ) as stream:
    yield stream


async def stream_checks() -> dict[str, list[tuple[int, int]]]:
  """Sample three books per reference with bounded waiting and owned subscriptions."""
  result: dict[str, list[tuple[int, int]]] = {}
  for market_id in MARKETS:
    samples: list[tuple[int, int]] = []
    async with depth_stream(market_id, levels=5) as stream:
      async for book in stream:
        assert 0 < len(book.bids) <= 5 and 0 < len(book.asks) <= 5
        samples.append((len(book.bids), len(book.asks)))
        if len(samples) == 3:
          break
    result[market_id] = samples
  return result


await asyncio.wait_for(stream_checks(), timeout=45)


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.


# %%
async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Re-key validated public Ticker rows by pair altname."""
  return await exchange.tickers(markets, settings=settings)


all_tickers = await tickers()
assert set(MARKETS) <= set(all_tickers)
{'count': len(all_tickers), 'references': await tickers(MARKETS)}


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Map public AssetPairs constraints and public fee schedules."""
  return await (await exchange.market(market_id)).rules(refetch=refetch)


{market_id: await rules(market_id) for market_id in MARKETS}


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.


# %%
async def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
) -> Sequence[Candle]:
  """Map typed OHLC tuples and filter opens to the SDK half-open window."""
  await asyncio.sleep(3)
  return await (await exchange.market(market_id)).candles(interval, start, end)


{market_id: await candles(market_id, '1m', start, end) for market_id in MARKETS}


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.


# %%
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


# %%
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
async def trades_history(market_id: str, /, start: datetime, end: datetime):
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.


# %%
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
async def position(market_id: str, /) -> Position:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `collateral`
#
# Fetch collateral.


# %%
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
async def available_notional(market_id: str, /):
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.


# %%
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Outside this credential-free public-data qualification."""
  raise NotImplementedError('Private account data or trading is outside this probe')


# not executed: private account data or trading is outside this probe


# %% [markdown]
# ## Coverage
#
# Status is one of `verified` (executed live, real data), `empty` (executed live, nothing to show on this account), `blocked` (a typed-client issue, titled in `typed-client-issues.md`), `not supported` (the venue has no such data) or `not attempted`.
#
# | method | status | note |
# |---|---|---|
# | `markets` | verified | 1,450 joined Spot altnames; BTC/ETH references present. |
# | `depth` | verified | BTC/ETH at 5 and 100 REST levels. |
# | `depth_stream` | verified | Three five-level books per BTC/ETH reference. |
# | `tickers` | verified | 1,450 rows and selected BTC/ETH snapshots. |
# | `rules` | verified | BTC/ETH public constraints and fee schedules. |
# | `fees` | not attempted | Private account data or trading is outside this probe. |
# | `candles` | verified | All six intervals on BTC/ETH; retention and fractional/forming bounds verified. |
# | `query_order` | not attempted | Private account data or trading is outside this probe. |
# | `open_orders` | not attempted | Private account data or trading is outside this probe. |
# | `trades_history` | not attempted | Private account data or trading is outside this probe. |
# | `trades_stream` | not attempted | Private account data or trading is outside this probe. |
# | `position` | not attempted | Private account data or trading is outside this probe. |
# | `collateral` | not attempted | Private account data or trading is outside this probe. |
# | `available_notional` | not attempted | Private account data or trading is outside this probe. |
# | `place_order` | not attempted | Private account data or trading is outside this probe. |
# | `cancel_order` | not attempted | Private account data or trading is outside this probe. |
# | `cancel_orders` | not attempted | Private account data or trading is outside this probe. |
# | `cancel_open_orders` | not attempted | Private account data or trading is outside this probe. |
# | `futures_markets` | verified | Released typed-kraken 0.4.0; full Futures qualification is in futures.py. |

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue
from sdk_dev.repo import repo_root

pairs = await venue.shared.load_pairs()
ids = Ids(
  spot_markets={f'spot:{m}' for m in listed},
  assets={
    asset
    for pair in pairs.values()
    for name in ['base', 'quote']
    if (asset := pair['info'].get(name))
  },
)
catalogue_gap = gap('kraken', ids, load_catalogue(root=repo_root()))
catalogue_gap

# %% [markdown]
# ## Candle retention and bounds
#
# Probe every SDK interval on both reference markets. Raw OHLC requests deliberately
# begin 1,000 intervals ago; the retained page must not be mistaken for archive data.


# %%
async def candle_checks(market_id: str) -> dict[CandleInterval, dict[str, int | str]]:
  """Measure each retained page and verify recent and out-of-retention SDK windows."""
  results: dict[CandleInterval, dict[str, int | str]] = {}
  epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
  market = await exchange.market(market_id)
  interval: CandleInterval
  for interval in INTERVALS:
    width = candle_width(interval)
    now = datetime.now(timezone.utc)
    current = epoch + ((now - epoch) // width) * width
    lower = current - width * 1000
    await asyncio.sleep(3)
    response = await market.call_kraken(
      lambda: client.spot.market_data.ohlc(
        market_id, interval=INTERVALS[interval], since=lower
      )
    )
    raw = response[market.meta['pair']['key']]
    assert not isinstance(raw, int)
    assert isinstance(response['last'], int)
    assert raw
    assert all(
      isinstance(row[0], datetime) and row[0].utcoffset() is not None for row in raw
    )
    assert all(isinstance(value, Decimal) for row in raw for value in row[1:7])
    assert all(isinstance(row[7], int) for row in raw)
    assert min(row[0] for row in raw) > lower
    recent = await candles(market_id, interval, current - width * 3, current)
    old = await candles(market_id, interval, lower, lower + width * 3)
    assert not old
    assert len(recent) == 3
    assert all(current - width * 3 <= row.time < current for row in recent)
    assert len(recent) == len({row.time for row in recent})
    assert all((row.time - epoch) % width == timedelta(0) for row in recent)
    assert all(
      row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high
      for row in recent
    )
    results[interval] = {
      'raw_rows': len(raw),
      'earliest': min(row[0] for row in raw).isoformat(),
      'latest': max(row[0] for row in raw).isoformat(),
      'recent_rows': len(recent),
      'old_rows': len(old),
    }
    print(market_id, interval, results[interval])
  return results


# %%
with Context().retried(NetworkError, RateLimited, max_retries=2, base_delay=3).use():
  btc_candles = await asyncio.wait_for(candle_checks('XBTUSD'), timeout=180)
btc_candles

# %%
with Context().retried(NetworkError, RateLimited, max_retries=2, base_delay=3).use():
  eth_candles = await asyncio.wait_for(candle_checks('ETHUSD'), timeout=180)
eth_candles


# %%
async def boundary_checks() -> dict[str, dict[str, int]]:
  """Check fractional lower bounds, equal bounds and inclusion of a forming hour."""
  result: dict[str, dict[str, int]] = {}
  current = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
  width = timedelta(hours=1)
  for market_id in MARKETS:
    recent = await candles(market_id, '1h', current - width * 3, current)
    fractional = await candles(
      market_id, '1h', current - width * 3 + timedelta(microseconds=1), current
    )
    forming = await candles(market_id, '1h', current, current + width)
    equal = await candles(market_id, '1h', current, current)
    assert len(recent) == 3 and len(fractional) == 2
    assert [row.time for row in fractional] == [
      row.time for row in recent if row.time > current - width * 3
    ]
    assert forming and all(row.time == current for row in forming)
    assert not equal
    result[market_id] = {
      'fractional_rows': len(fractional),
      'forming_rows': len(forming),
      'equal_rows': len(equal),
    }
  return result


with Context().retried(NetworkError, RateLimited, max_retries=2, base_delay=3).use():
  boundary_results = await asyncio.wait_for(boundary_checks(), timeout=90)
boundary_results

# %% [markdown]
# ## Released Futures discovery
#
# Public Futures endpoints shipped in typed-kraken 0.4.0. Detailed endpoint and SDK
# qualification is in `futures.py`; this cell rechecks the formerly blocked discovery.


# %%
async def futures_markets() -> Sequence[str]:
  """Verify the released Futures discovery; detailed qualification is in futures.py."""
  return await (await venue.exchange('perp')).markets()


len(await futures_markets())


# %%
await stack.aclose()
