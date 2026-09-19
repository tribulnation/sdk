# %% [markdown]
# # deribit `market` PoC
#
# Maps `typed_deribit` onto the SDK `market` surface, one method per cell, each executed live. The rules, and how a typed-client issue is reported in `typed-client-issues.md`, are in `.agents/skills/sdk-poc/SKILL.md`.

# %%
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing_extensions import (
  Any,
  AsyncGenerator,
  AsyncIterable,
  Collection,
  Mapping,
  Sequence,
)
from tribulnation.deribit import DeribitMarket
from sdk_dev.repo import repo_root
from tribulnation.sdk.market import (
  Book,
  CandleInterval,
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

venue = await DeribitMarket.new().__aenter__()
client = venue.shared.client
MARKETS = [
  'spot:BTC_USDC',
  'spot:BTC_USDT',
  'perp:BTC_USDC-PERPETUAL',
  'perp:ETH_USDC-PERPETUAL',
]
end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
start = end - timedelta(days=7)


# %% [markdown]
# ## Surface
#
# What the client exposes. Widen or narrow the filter until every endpoint the mapping below uses is listed here.

# %%
from sdk_dev.surface import surface

print(
  surface(
    'typed_deribit', 'Deribit', grep=r'book|ticker|index|funding|instrument|tradingview'
  )
)


# %% [markdown]
# ## `markets`
#
# List available markets.


# %%
async def markets() -> Sequence[str]:
  """Discover native active spot and linear perpetual IDs."""
  return [
    f'{e["id"]}:{symbol}'
    for e in await venue.exchanges()
    for symbol in await (await venue.exchange(e['id'])).markets()
  ]


listed = await markets()
print({e: sum(m.startswith(e + ':') for m in listed) for e in ['spot', 'perp']})
listed


# %% [markdown]
# ## `depth`
#
# Fetch the market order book.


# %%
async def depth(market_id: str, /, *, levels: int | None = None) -> Book:
  """Map native base-unit books through the packaged implementation."""
  return await venue.depth(market_id, levels=levels)


for m in MARKETS:
  for levels in [1, 5, 20, 100]:
    book = await depth(m, levels=levels)
    print(m, levels, len(book.bids), len(book.asks), book.bids[:1], book.asks[:1])


# %% [markdown]
# ## `depth_stream`
#
# Subscribe to the market order book.


# %%
def depth_stream(
  market_id: str,
  /,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Read shared public full snapshots through the SDK subscription contract."""
  return venue.depth_stream(
    market_id, levels=levels, queue_size=queue_size, overflow=overflow
  )


for m in MARKETS:
  async with depth_stream(m, levels=5) as stream:
    iterator = aiter(stream)
    for _ in range(1):
      book = await asyncio.wait_for(anext(iterator), 20)
      print(m, len(book.bids), len(book.asks))


# %% [markdown]
# ## `tickers`
#
# Fetch a ticker snapshot for many markets at once.


# %%
async def tickers(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, Ticker]:
  """Product-scoped summaries omit unrelated option records."""
  result: dict[str, Ticker] = {}
  for exchange_id in ['spot', 'perp']:
    exchange = await venue.exchange(exchange_id)
    selected = (
      None
      if markets is None
      else [m.split(':', 1)[1] for m in markets if m.startswith(exchange_id + ':')]
    )
    result.update(
      {
        f'{exchange_id}:{name}': row
        for name, row in (await exchange.tickers(selected)).items()
      }
    )
  return result


all_tickers = await tickers()
assert set(all_tickers) == set(listed)
print('all', len(all_tickers))
await tickers(MARKETS)


# %% [markdown]
# ## `rules`
#
# Fetch the market rules.


# %%
# not executed: fee denomination and quantity-step fallback are unqualified
async def rules(market_id: str, /, *, refetch: bool = False) -> Rules:
  """Keep unqualified public rules explicit rather than guessing fee or size fields."""
  raise NotImplementedError('Public rules are not qualified')


# %% [markdown]
# ## `fees`
#
# Fetch the selected market's account rates without a standard-rate fallback.


# %%
# not executed: private account methods and trading are outside this public scope
async def fees(market_id: str, /, *, refetch: bool = False) -> Fees:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `candles`
#
# Fetch the market's historical trade candles.


# %%
def candles(
  market_id: str, /, interval: CandleInterval, start: datetime, end: datetime
):
  """Native WebSocket candles with 1000-open SDK windows; 08:00 UTC daily candles are excluded and half-open bounds."""
  return venue.candles(market_id, interval, start, end)


widths: dict[CandleInterval, timedelta] = {
  '1m': timedelta(minutes=1),
  '5m': timedelta(minutes=5),
  '15m': timedelta(minutes=15),
  '1h': timedelta(hours=1),
}
for m in ['spot:BTC_USDT', 'perp:BTC_USDC-PERPETUAL', 'perp:ETH_USDC-PERPETUAL']:
  for interval, width in widths.items():
    lower = end - width * 1002
    pages = [page async for page in candles(m, interval, lower, end)]
    rows = [row for page in pages for row in page]
    assert len(pages) == 2
    assert len(rows) == len({r.time for r in rows})
    assert all(lower <= r.time < end for r in rows)
    assert all(
      (r.time - datetime(1970, 1, 1, tzinfo=timezone.utc)) % width == timedelta(0)
      for r in rows
    )
    print(m, interval, len(rows), [len(p) for p in pages])

for m in MARKETS:
  market = await venue.market(m)
  print(m, sorted(market.CANDLE_INTERVALS))
  try:
    await market.candles('4h', start, end)
  except ValueError:
    print('4h explicitly unsupported')


# %% [markdown]
# ## `query_order`
#
# Fetch the state of the order with the given ID.


# %%
# not executed: private account methods and trading are outside this public scope
async def query_order(market_id: str, /, id: str) -> OrderState | None:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `open_orders`
#
# Fetch your currently open orders.


# %%
# not executed: private account methods and trading are outside this public scope
async def open_orders(market_id: str, /) -> Sequence[OrderState]:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `trades_history`
#
# Fetch your trades history.


# %%
# not executed: private account methods and trading are outside this public scope
async def trades_history(market_id: str, /, start: datetime, end: datetime):
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `trades_stream`
#
# Subscribe to your real-time trades.


# %%
# not executed: private account methods and trading are outside this public scope
async def trades_stream(
  market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
) -> AsyncGenerator[AsyncIterable[Trade]]:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `position`
#
# Fetch your open position in the market.


# %%
# not executed: private account methods and trading are outside this public scope
async def position(market_id: str, /) -> Position:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `available_notional`
#
# Fetch the max. notional position you can open.


# %%
# not executed: private account methods and trading are outside this public scope
async def available_notional(market_id: str, /):
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `place_order`
#
# Place an order in the market.


# %%
# not executed: private account methods and trading are outside this public scope
async def place_order(
  market_id: str, /, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `cancel_order`
#
# Cancel an order in the market.


# %%
# not executed: private account methods and trading are outside this public scope
async def cancel_order(market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `cancel_orders`
#
# Cancel multiple orders in the market.


# %%
# not executed: private account methods and trading are outside this public scope
async def cancel_orders(
  market_id: str, /, ids: Sequence[str], *, settings: Settings = {}
) -> Any:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `cancel_open_orders`
#
# Cancel all open orders in the market.


# %%
# not executed: private account methods and trading are outside this public scope
async def cancel_open_orders(market_id: str, /, *, settings: Settings = {}) -> Any:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `index`
#
# Fetch the market index price.


# %%
async def index(market_id: str, /, *, settings: Settings = {}) -> Decimal:
  """Use the ticker's native index, never a midpoint."""
  return await venue.index(market_id)


{m: await index(m) for m in MARKETS if m.startswith('perp:')}


# %% [markdown]
# ## `next_funding`
#
# Fetch the next funding rate and time.


# %%
# not executed: continuous funding supplies no qualified next-payment forecast
async def next_funding(market_id: str, /) -> NextFunding:
  """No fabricated hourly payment boundary."""
  raise NotImplementedError('Continuous accrual is not scheduled funding')


# %% [markdown]
# ## `perp_stats`
#
# Fetch a pricing and funding snapshot for many markets at once.


# %%
async def perp_stats(
  markets: Collection[str] | None = None, *, settings: Settings = {}
) -> Mapping[str, PerpStats]:
  """Native index, mark and base interest, with unsupported funding fields unset."""
  return await (await venue.perp_exchange('perp')).perp_stats(
    markets, settings=settings
  )


stats = await perp_stats()
assert set(stats) == set(await (await venue.perp_exchange('perp')).markets())
print(len(stats))
{k: stats[k] for k in ['BTC_USDC-PERPETUAL', 'ETH_USDC-PERPETUAL']}


# %% [markdown]
# ## `funding_rates`
#
# Fetch the market's historical funding rates.


# %%
# not executed: hourly accrual observations do not establish SDK payment-time semantics
async def funding_rates(
  market_id: str, /, start: datetime | None = None, end: datetime | None = None
):
  """Keep hourly observations separate from discrete payment rates."""
  raise NotImplementedError('No qualified discrete funding payment series')


# %% [markdown]
# ## `funding_payments`
#
# Fetch your funding payments history.


# %%
# not executed: private account methods and trading are outside this public scope
async def funding_payments(market_id: str, /, start: datetime, end: datetime):
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `perp_position`
#
# Fetch your open position in the perpetual market.


# %%
# not executed: private account methods and trading are outside this public scope
async def perp_position(market_id: str, /) -> PerpPosition:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `collateral`
#
# Fetch collateral (defers to `perp_collateral`).


# %%
# not executed: private account methods and trading are outside this public scope
async def collateral(market_id: str | None = None, /) -> Collateral:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## `perp_collateral`
#
# Fetch perpetual collateral.


# %%
# not executed: private account methods and trading are outside this public scope
async def perp_collateral(market_id: str | None = None, /) -> PerpCollateral:
  """Private account methods and trading are intentionally unsupported."""
  raise NotImplementedError('Deribit Market supports public data only')


# %% [markdown]
# ## Coverage
#
# | method | status | note |
# |---|---|---|
# | markets, tickers | verified | 19 spot and 126 linear perpetuals; exact native IDs |
# | depth, depth_stream | verified | Mainnet spot and linear; native base quantities |
# | candles | verified | Four intervals over 1000-open page boundaries; routed spot, 4h and 08:00 UTC daily unsupported |
# | index, perp_stats | verified | Native ticker index, mark and base interest |
# | rules | not attempted | Fee denomination and quantity-step fallback unqualified |
# | next_funding, funding_rates | not supported | Continuous accrual observations do not establish discrete SDK payment semantics |
# | fees, query_order, open_orders, trades_history, trades_stream | not attempted | Private methods outside scope |
# | position, available_notional, collateral, perp_position, perp_collateral | not attempted | Private methods outside scope |
# | place_order, cancel_order, cancel_orders, cancel_open_orders, funding_payments | not attempted | Private methods outside scope |
#
# The broad, unfiltered summary endpoint has a typed response defect documented in
# `typed-client-issues.md`. Supported product-scoped calls validate. Candle HTTP calls
# return method-not-found; native typed WebSocket calls validate without a schema bypass.
#

# %% [markdown]
# ## Catalogue
#
# Every ID the verified methods returned, minus what the catalogue translates for this platform. Anything listed is a catalogue addition to make, not something to rename here: the SDK emits venue-native IDs and the catalogue maps them.

# %%
from sdk_dev.catalogue import Ids, gap, load_catalogue

listed = await markets()
rows = await venue.shared.symbols()
ids = Ids(
  spot_markets={m for m in listed if m.startswith('spot:')},
  perp_markets={m for m in listed if m.startswith('perp:')},
  assets={
    asset for r in rows.values() for asset in [r['base_currency'], r['quote_currency']]
  },
)
gap(
  'deribit',
  ids,
  load_catalogue(repo_root().parent / 'catalogue' / 'data'),
)

# %% [markdown]
# ## Historical samples and public transport observations

# %%
from typed_deribit.core import ApiError

for year in [2020, 2023, 2025]:
  for m in ['spot:BTC_USDT', 'perp:BTC_USDC-PERPETUAL']:
    lower = datetime(year, 1, 2, tzinfo=timezone.utc)
    rows = await candles(m, '1m', lower, lower + timedelta(hours=3))
    print(year, m, len(rows))

try:
  await client.market_data.get_tradingview_chart_data(
    'BTC_USDC-PERPETUAL', start_timestamp=start, end_timestamp=end, resolution='60'
  )
except ApiError as error:
  print('HTTP candle transport:', error)

for m in ['BTC_USDC-PERPETUAL', 'ETH_USDC-PERPETUAL']:
  native = await client.market_data.get_funding_rate_history(
    m, start_timestamp=start, end_timestamp=end
  )
  print(
    'Native hourly observations (not SDK funding):',
    m,
    len(native),
    native[:1],
    native[-1:],
  )
row = await client.market_data.get_tradingview_chart_data(
  'BTC_USDC-PERPETUAL',
  start_timestamp=start,
  end_timestamp=end,
  resolution='1D',
  transport='ws',
)
print(
  'Native daily opens (unsupported by SDK midnight alignment):',
  [datetime.fromtimestamp(t / 1000, timezone.utc) for t in row.get('ticks', [])][:3],
)


# %%
from typed_core.exceptions import ValidationError
from typing_extensions import Literal

try:
  await client.market_data.get_book_summary_by_currency(currency='BTC')
except ValidationError as error:
  print('Unfiltered public summary defect:', str(error)[:900])
scopes: list[tuple[str, Literal['spot', 'future']]] = [
  ('BTC', 'spot'),
  ('USDC', 'future'),
]
for currency, kind in scopes:
  summaries = await client.market_data.get_book_summary_by_currency(
    currency=currency, kind=kind
  )
  print('Supported product summary validates:', currency, kind, len(summaries))


# %%
await venue.__aexit__(None, None, None)
