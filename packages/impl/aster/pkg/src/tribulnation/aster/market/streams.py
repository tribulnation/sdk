"""Shared book and fill streams, including account listen-key renewal."""

import asyncio
from contextlib import AsyncExitStack, suppress
from typing_extensions import (
  AsyncIterable,
  AsyncIterator,
  Awaitable,
  Callable,
  TypeVar,
)
from typed_aster.schemas import (
  DepthUpdate,
  ExecutionReport,
  OutboundAccountPosition,
)
from typed_aster.futures.user_stream.events import FuturesUserEvent, OrderUpdate
from tribulnation.sdk.core import MissingData, NetworkError, Subscription
from tribulnation.sdk.market import Book, Trade
from ..core import Scope, Shared, wrap_exceptions

T = TypeVar('T')
RENEWAL_INTERVAL = 25 * 60
"""Seconds between keepalives; listen keys expire after 60 minutes."""


def parse_book(row: DepthUpdate) -> Book:
  """Convert a partial-depth snapshot; quantities are in base units."""
  return Book(
    bids=[Book.Entry(*r) for r in row['b']], asks=[Book.Entry(*r) for r in row['a']]
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


@wrap_exceptions
async def connect_books(
  shared: Shared, scope: Scope, symbol: str
) -> Subscription.Context[Book]:
  """Open one 20-level stream per symbol, shared by every subscriber."""
  manager = (
    shared.client.futures.streams.partial_depth(symbol.lower(), levels=20)
    if scope == 'perp'
    else shared.client.spot.streams.partial_depth(
      symbol.lower(), levels=20, speed='100ms'
    )
  )
  stream = await manager.map(parse_book)
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
