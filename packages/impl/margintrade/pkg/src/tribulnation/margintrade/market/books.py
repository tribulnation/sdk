"""Order books: REST `l2Book` snapshots and one shared `l2Book` stream per coin."""

from contextlib import asynccontextmanager

from typing_extensions import AsyncIterable, AsyncIterator
from tribulnation.sdk.core import OverflowPolicy, Subscription, exception_wrapper
from tribulnation.sdk.market import Book

from ..core import Shared
from .common import levels


async def depth(shared: Shared, coin: str, *, levels_cap: int | None = None) -> Book:
  """The aggregated book snapshot (the venue's own levels, best first)."""
  raw = await shared.call(lambda: shared.client.info.l2_book(coin))
  bids, asks = raw['levels']
  book = Book(bids=levels(bids), asks=levels(asks), time=raw['time'])
  return book if levels_cap is None else book.limit(levels_cap)


def subscription(shared: Shared, coin: str) -> Subscription[Book]:
  """One upstream `l2Book` feed per coin; every push is a full snapshot."""
  if coin not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Subscribe; each push replaces the previous book."""
      stream = await shared.client.streams.l2_book(coin)

      @exception_wrapper()
      async def books() -> AsyncIterator[Book]:
        """Convert each snapshot."""
        async for update in stream:
          bids, asks = update['levels']
          yield Book(bids=levels(bids), asks=levels(asks), time=update['time'])

      return Subscription.Context(books(), exception_wrapper()(stream.unsubscribe))

    shared.books[coin] = Subscription(connect)
  return shared.books[coin]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  coin: str,
  *,
  levels_cap: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels_cap`."""
  upstream = subscription(shared, coin)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Copy before handing out: subscribers share each snapshot."""
    async for book in books:
      yield book.copy() if levels_cap is None else book.copy().limit(levels_cap)

  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
