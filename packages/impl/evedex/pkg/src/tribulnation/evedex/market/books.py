"""Order books: REST snapshots and one shared WebSocket book per instrument.

Both serve the aggregated book, at most 100 levels per side, stamped with the venue's
book time. Every `orderBook-<instrument>-<round>` publication is the whole book, not a
delta. The grouping step `0.1` is the venue's finest: it leaves every instrument's
levels at its own tick (XRPUSD's `0.0001` levels, ETHUSD's `0.01`), identical to the
REST book (2026-11-19).
"""

from contextlib import AsyncExitStack, asynccontextmanager

from typing_extensions import AsyncIterator, Sequence
from typed_evedex.exchange.market.order_book import OrderBookAsk, OrderBookBid
from typed_evedex.streams.order_book import (
  OrderBookLevelAsksItem,
  OrderBookLevelBidsItem,
  OrderBookUpdate,
)
from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, detached_books

from ..core import Shared, wrap_exceptions

ROUND = '0.1'
"""The book channel's finest grouping step."""


def entries(
  rows: Sequence[OrderBookAsk]
  | Sequence[OrderBookBid]
  | Sequence[OrderBookLevelAsksItem]
  | Sequence[OrderBookLevelBidsItem],
) -> list[Book.Entry]:
  """Book entries from aggregated price levels."""
  return [Book.Entry(r['price'], r['quantity']) for r in rows]


def frame_book(frame: OrderBookUpdate) -> Book:
  """A channel publication as the whole book."""
  book = frame['orderBook']
  return Book(bids=entries(book['bids']), asks=entries(book['asks']), time=book['t'])


async def depth(shared: Shared, instrument: str, *, levels: int | None = None) -> Book:
  """The aggregated REST book, best first, at most 100 levels per side.

  Args:
    shared: The owner of the client.
    instrument: The instrument's name.
    levels: Keep at most this many levels per side.
  """
  await shared.instrument(instrument)
  raw = await shared.call(
    lambda: shared.client.exchange.market.order_book(instrument=instrument)
  )
  book = Book(bids=entries(raw['bids']), asks=entries(raw['asks']), time=raw['t'])
  return book if levels is None else book.limit(levels)


def subscription(shared: Shared, instrument: str) -> Subscription[Book]:
  """One upstream book per instrument, on the client's one connection."""
  if instrument not in shared.books:

    @wrap_exceptions
    async def connect() -> Subscription.Context[Book]:
      """Subscribe to the instrument's book channel."""
      manager = shared.client.streams.order_book(instrument, round=ROUND)
      stack = AsyncExitStack()
      stream = await stack.enter_async_context(manager)

      @wrap_exceptions
      async def frames() -> AsyncIterator[Book]:
        """Every publication of the channel, as a book."""
        async for frame in stream:
          yield frame_book(frame).frozen()

      @wrap_exceptions
      async def close():
        """Unsubscribe."""
        await stack.aclose()

      return Subscription.Context(frames(), close)

    shared.books[instrument] = Subscription(connect)
  return shared.books[instrument]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  instrument: str,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`.

  Args:
    shared: The owner of the fan-outs.
    instrument: The instrument's name.
    levels: Keep at most this many levels per side.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  await shared.instrument(instrument)
  upstream = subscription(shared, instrument)
  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield detached_books(stream, levels)
