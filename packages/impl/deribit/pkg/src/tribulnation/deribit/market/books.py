"""Native base-unit spot and linear perpetual books with shared snapshot feeds."""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing_extensions import AsyncIterable, AsyncIterator, Literal
from tribulnation.sdk.core import OverflowPolicy, Subscription, exception_wrapper
from tribulnation.sdk.market import Book
from .common import Shared


def parse_book(
  bids: list[tuple[float, float]], asks: list[tuple[float, float]]
) -> Book:
  """Translate both sides without multiplying already-base quantities by contract size."""
  return Book(
    bids=[
      Book.Entry(Decimal(str(p)), Decimal(str(q)))
      for p, q in sorted(bids, reverse=True)
    ],
    asks=[Book.Entry(Decimal(str(p)), Decimal(str(q))) for p, q in sorted(asks)],
  )


def check_levels(levels: int | None, *, maximum: int) -> int:
  """Validate the requested depth, defaulting to twenty levels."""
  size = 20 if levels is None else levels
  if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= maximum:
    raise ValueError(f'Deribit supports 1-{maximum} levels for this read')
  return size


async def depth(shared: Shared, symbol: str, *, levels: int | None = None) -> Book:
  """Request the smallest sufficient native depth up to one hundred levels."""
  size = check_levels(levels, maximum=100)
  choices: tuple[Literal[1, 5, 10, 20, 50, 100], ...] = (1, 5, 10, 20, 50, 100)
  native: Literal[1, 5, 10, 20, 50, 100] = next(n for n in choices if n >= size)
  row = await shared.call(
    lambda: shared.client.market_data.get_order_book(symbol, depth=native)
  )
  return parse_book(row['bids'], row['asks']).limit(size)


def subscription(shared: Shared, symbol: str) -> Subscription[Book]:
  """Reuse one public twenty-level full-snapshot source per native instrument."""
  if symbol not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Translate acquisition, iteration and unsubscribe errors at their boundaries."""
      stream = await shared.client.streams.market_data.book_grouped(
        symbol, group='none', depth='20', interval='100ms'
      )

      @exception_wrapper()
      async def updates() -> AsyncIterator[Book]:
        """Each notification replaces the full book, rather than applying deltas."""
        async for row in stream:
          yield parse_book(row['bids'], row['asks'])

      return Subscription.Context(updates(), exception_wrapper()(stream.unsubscribe))

    shared.books[symbol] = Subscription(connect)
  return shared.books[symbol]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  symbol: str,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out fresh, independently trimmed books with bounded subscriber queues."""
  size = check_levels(levels, maximum=20)
  source = subscription(shared, symbol)

  async def trimmed(stream: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Do not expose a mutable book shared with another subscriber."""
    async for book in stream:
      yield Book(
        bids=[Book.Entry(e.price, e.qty) for e in book.bids[:size]],
        asks=[Book.Entry(e.price, e.qty) for e in book.asks[:size]],
      )

  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
