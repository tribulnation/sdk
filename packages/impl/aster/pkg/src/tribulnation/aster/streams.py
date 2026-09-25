"""Validated native book/fill streams with shared ownership and lease renewal."""

import asyncio
from contextlib import AsyncExitStack, suppress
from typing_extensions import AsyncIterable, AsyncIterator, TypeVar
from typed_aster.schemas import DepthUpdate, ExecutionReport
from typed_aster.futures.user_stream.events import OrderUpdate
from tribulnation.sdk.core import NetworkError, Subscription
from tribulnation.sdk.market import Book, Trade
from .core import Scope, Shared, wrap_exceptions

T = TypeVar('T')


def parse_book(row: DepthUpdate) -> Book:
  """Convert a native complete partial-depth snapshot in base units."""
  return Book(
    bids=[Book.Entry(*r) for r in row['b']], asks=[Book.Entry(*r) for r in row['a']]
  )


def parse_fill(row: OrderUpdate | ExecutionReport) -> Trade:
  """Map the last fill rather than the order's cumulative execution quantity."""
  if (
    'l' not in row
    or 'L' not in row
    or 'T' not in row
    or 't' not in row
    or 'm' not in row
  ):
    raise NotImplementedError('Aster fill event lacks native last-fill fields')
  fee = None
  if 'n' in row and 'N' in row:
    fee = Trade.Fee(amount=row['n'], asset=row['N'])
  elif 'n' in row or 'N' in row:
    raise NotImplementedError('Aster commission amount and asset must arrive together')
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
  """Translate failures raised during iteration, not just subscription setup."""
  async for item in stream:
    yield item


@wrap_exceptions
async def connect_books(
  shared: Shared, scope: Scope, symbol: str
) -> Subscription.Context[Book]:
  """Open one native top-20 stream, releasing it when its last subscriber leaves."""
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
  stream: AsyncIterable[T], renewal: asyncio.Task[None]
) -> AsyncIterator[T]:
  """Fail subscribers immediately if their listen-key renewal task fails."""
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


@wrap_exceptions
async def connect_trades(
  shared: Shared, scope: Scope
) -> Subscription.Context[tuple[str, Trade]]:
  """Acquire a renewable account stream, rolling back the lease on setup failure."""
  stack = AsyncExitStack()
  client = shared.client
  try:
    if scope == 'perp':
      key = (await shared.call_aster(client.futures.listen_key.start))['listenKey']
      stack.push_async_callback(shared.call_aster, client.futures.listen_key.close)
      upstream = await stack.enter_async_context(client.futures.user_stream.events(key))

      async def keepalive():
        """Renew the perpetual listen-key lease before it expires."""
        while True:
          await asyncio.sleep(25 * 60)
          await shared.call_aster(client.futures.listen_key.keepalive)

      async def fills() -> AsyncIterator[tuple[str, Trade]]:
        """Filter perpetual status/account events without inventing trades."""
        async for event in upstream:
          if event['e'] == 'listenKeyExpired':
            raise NetworkError('Aster listen key expired')
          if event['e'] == 'ORDER_TRADE_UPDATE' and event['o']['x'] == 'TRADE':
            yield event['o']['s'], parse_fill(event['o'])
    else:
      key = (await shared.call_aster(client.spot.listen_key.start))['listenKey']
      stack.push_async_callback(
        shared.call_aster, lambda: client.spot.listen_key.close(key)
      )
      spot_upstream = await stack.enter_async_context(
        client.spot.user_stream.events(key)
      )

      async def keepalive():
        """Renew the spot listen-key lease before it expires."""
        while True:
          await asyncio.sleep(25 * 60)
          await shared.call_aster(lambda: client.spot.listen_key.keepalive(key))

      async def fills() -> AsyncIterator[tuple[str, Trade]]:
        """Keep native spot fills; account and order-status changes are not trades."""
        async for event in spot_upstream:
          if event['e'] == 'executionReport' and event['x'] == 'TRADE':
            yield event['s'], parse_fill(event)

    renewal = asyncio.create_task(keepalive())

    async def cancel_renewal():
      """Reap the renewal task on last-unsubscribe or owner teardown."""
      renewal.cancel()
      with suppress(asyncio.CancelledError):
        await renewal

    stack.push_async_callback(cancel_renewal)
    return Subscription.Context(
      translated(with_renewal(fills(), renewal)), wrap_exceptions(stack.aclose)
    )
  except BaseException:
    await stack.aclose()
    raise
