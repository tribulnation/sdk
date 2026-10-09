"""Shared book and fill streams, including account listen-key renewal."""

import asyncio
from contextlib import AsyncExitStack, suppress
from datetime import datetime
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  Mapping,
  TypeVar,
)
from typed_core.util import StreamManager
from typed_aster.core import timestamp_millis
from typed_aster.futures.market.depth import OrderBookResponse
from typed_aster.futures.streams.schemas import FuturesBookTickerEvent
from typed_aster.schemas import (
  BookTickerEvent,
  DepthUpdate,
  ExecutionReport,
  OrderBook,
  OutboundAccountPosition,
)
from typed_aster.futures.user_stream.events import FuturesUserEvent, OrderUpdate
from tribulnation.sdk.core import MissingData, NetworkError, Subscription
from tribulnation.sdk.market import Book, Settings, Trade
from tribulnation.sdk.util import epoch_time
from ..core import DepthSource, Scope, Shared, wrap_exceptions

T = TypeVar('T')
SOURCE_LEVELS: Mapping[DepthSource, int] = {'depth': 20, 'fast': 5, 'bbo': 1}
"""Levels per side each depth source delivers; REST `depth` trims `'fast'` and `'bbo'`
to the same shape."""
RENEWAL_INTERVAL = 25 * 60
"""Seconds between keepalives; listen keys expire after 60 minutes."""


def depth_source(settings: Settings) -> DepthSource:
  """The `aster.depth_source` setting, defaulting to `'depth'`.

  Args:
    settings: Venue-keyed settings; only the `aster` key is read.

  Raises:
    ValueError: The setting names no known source.
  """
  source = settings.get('aster', {}).get('depth_source', 'depth')
  if source not in SOURCE_LEVELS:
    raise ValueError(
      f'Unknown Aster depth_source {source!r}; expected one of {list(SOURCE_LEVELS)}'
    )
  return source


def book_time(
  row: DepthUpdate
  | OrderBook
  | OrderBookResponse
  | FuturesBookTickerEvent
  | BookTickerEvent,
) -> datetime | None:
  """The time a book snapshot was current: its event/output time `E`, else `T`.

  Partial-depth pushes and REST `depth` are full top-N snapshots, not diffs, so each is
  the book as of when Aster produced it (`E`, at or after the transaction time `T` of
  the last change it includes). A message without `E` falls back to `T`; None when
  neither is present.
  """
  time = row.get('E', row.get('T'))
  return None if time is None else epoch_time(time, timestamp_millis)


def parse_book(row: DepthUpdate) -> Book:
  """Convert a partial-depth snapshot; quantities are in base units."""
  return Book(
    bids=[Book.Entry(*r) for r in row['b']],
    asks=[Book.Entry(*r) for r in row['a']],
    time=book_time(row),
  )


def parse_bbo(row: FuturesBookTickerEvent | BookTickerEvent) -> Book:
  """Convert a `bookTicker` push into a one-level book, timed by its event time `E`.

  Each push is a full best bid/ask snapshot, so it takes `E` like partial depth, else
  `T`; spot pushes may carry neither, leaving the time None. Aster pushes only when
  the best level changes, so `E` stays put on a quiet book. A side with a
  zero price or quantity (an empty side) becomes an empty list.
  """
  bid = Book.Entry(Decimal(row['b']), Decimal(row['B']))
  ask = Book.Entry(Decimal(row['a']), Decimal(row['A']))
  return Book(
    bids=[bid] if bid.price > 0 and bid.qty > 0 else [],
    asks=[ask] if ask.price > 0 and ask.qty > 0 else [],
    time=book_time(row),
  )


def parse_fill(row: OrderUpdate | ExecutionReport) -> Trade:
  """Map an event's last fill, not the order's cumulative execution.

  Raises:
    MissingData: The event lacks a last-fill field, or has a fee amount without its
      asset (or vice versa). An incomplete fill is never emitted.
  """
  if 'l' not in row or 'L' not in row or 'T' not in row or 't' not in row:
    raise MissingData(
      'Aster fill lacks its last fill', market_id=row['s'], field='l/L/T/t'
    )
  if 'm' not in row:
    raise MissingData('Aster fill lacks its maker flag', market_id=row['s'], field='m')
  fee = None
  if 'n' in row and 'N' in row:
    fee = Trade.Fee(amount=row['n'], asset=row['N'])
  elif 'n' in row or 'N' in row:
    raise MissingData(
      'Aster fill has an incomplete commission', market_id=row['s'], field='n/N'
    )
  return Trade(
    id=str(row['t']),
    order_id=str(row['i']),
    client_order_id=row['c'] or None,
    price=row['L'],
    qty=row['l'] if row['S'] == 'BUY' else -row['l'],
    time=row['T'],
    maker=row['m'],
    fee=fee,
    details=row,
  )


@wrap_exceptions
async def translated(stream: AsyncIterable[T]) -> AsyncIterator[T]:
  """Translate failures raised while iterating, not only during setup."""
  async for item in stream:
    yield item


def depth_feed(
  shared: Shared, scope: Scope, symbol: str, source: DepthSource
) -> StreamManager[Book, Any, Any]:
  """The native stream behind one depth source, parsed into books.

  Args:
    shared: The owner of the client.
    scope: The exchange.
    symbol: The native symbol.
    source: Which feed to subscribe to; see `Settings.depth_source`.
  """
  name = symbol.lower()
  if scope == 'perp':
    streams = shared.client.futures.streams
    if source == 'bbo':
      return streams.book_ticker(name).map(parse_bbo)
    if source == 'fast':
      return streams.partial_depth_speed(name, levels=5, speed='100ms').map(parse_book)
    return streams.partial_depth(name, levels=20).map(parse_book)
  spot = shared.client.spot.streams
  if source == 'bbo':
    return spot.book_ticker(name).map(parse_bbo)
  levels = 5 if source == 'fast' else 20
  return spot.partial_depth(name, levels=levels, speed='100ms').map(parse_book)


@wrap_exceptions
async def connect_books(
  shared: Shared, scope: Scope, symbol: str, source: DepthSource
) -> Subscription.Context[Book]:
  """Open one stream per symbol and source, shared by every subscriber."""
  stream = await depth_feed(shared, scope, symbol, source)
  return Subscription.Context(translated(stream), wrap_exceptions(stream.unsubscribe))


async def with_renewal(
  stream: AsyncIterable[T], renewal: 'asyncio.Task[None]'
) -> AsyncIterator[T]:
  """Fail the stream as soon as its listen-key renewal fails, even while idle."""
  iterator = aiter(stream)
  while True:
    pending = asyncio.ensure_future(anext(iterator))
    try:
      await asyncio.wait((pending, renewal), return_when=asyncio.FIRST_COMPLETED)
      if renewal.done():
        await renewal
        raise NetworkError('Aster listen-key renewal stopped')
      try:
        item = pending.result()
      except StopAsyncIteration:
        return
    finally:
      if not pending.done():
        pending.cancel()
        with suppress(asyncio.CancelledError):
          await pending
    yield item


async def perp_fills(
  events: AsyncIterable[FuturesUserEvent],
) -> AsyncIterator[tuple[str, Trade]]:
  """Keep perpetual trade executions; order-status and account events are not fills."""
  async for event in events:
    if event['e'] == 'listenKeyExpired':
      raise NetworkError('Aster listen key expired')
    if event['e'] == 'ORDER_TRADE_UPDATE' and event['o']['x'] == 'TRADE':
      yield event['o']['s'], parse_fill(event['o'])


async def spot_fills(
  events: AsyncIterable[OutboundAccountPosition | ExecutionReport],
) -> AsyncIterator[tuple[str, Trade]]:
  """Keep spot trade executions; balance and order-status events are not fills."""
  async for event in events:
    if event['e'] == 'executionReport' and event['x'] == 'TRADE':
      yield event['s'], parse_fill(event)


async def keep_alive(shared: Shared, renew: Callable[[], Awaitable[object]]):
  """Renew a listen key until cancelled."""
  while True:
    await asyncio.sleep(RENEWAL_INTERVAL)
    await shared.call(renew)


@wrap_exceptions
async def connect_trades(
  shared: Shared, scope: Scope
) -> Subscription.Context[tuple[str, Trade]]:
  """Lease one account stream per exchange; the lease is released on unsubscribe."""
  stack = AsyncExitStack()
  try:
    if scope == 'perp':
      futures = shared.client.futures
      key = (await shared.call(futures.listen_key.start))['listenKey']
      stack.push_async_callback(shared.call, futures.listen_key.close)
      renew: Callable[[], Awaitable[object]] = futures.listen_key.keepalive
      events = await stack.enter_async_context(futures.user_stream.events(key))
      fills = perp_fills(events)
    else:
      spot = shared.client.spot
      key = (await shared.call(spot.listen_key.start))['listenKey']
      stack.push_async_callback(shared.call, lambda: spot.listen_key.close(key))
      renew = lambda: spot.listen_key.keepalive(key)
      events = await stack.enter_async_context(spot.user_stream.events(key))
      fills = spot_fills(events)
    renewal = asyncio.create_task(keep_alive(shared, renew))

    async def stop_renewal():
      """Reap the renewal task before the lease is closed."""
      renewal.cancel()
      with suppress(asyncio.CancelledError):
        await renewal

    stack.push_async_callback(stop_renewal)
    return Subscription.Context(
      translated(with_renewal(fills, renewal)), wrap_exceptions(stack.aclose)
    )
  except BaseException:
    await stack.aclose()
    raise
