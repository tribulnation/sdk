"""Order books: REST snapshots and one shared WebSocket book per market.

A RISEx client holds one subscription per channel, so each market's book stream opens
its own credential-free client (and connection), owned by the market's shared
subscription and closed with it.
"""

from contextlib import AsyncExitStack, asynccontextmanager

from typing_extensions import AsyncIterator, Sequence
from typed_risex.schemas import BookLevel, PriceLevel
from typed_risex.streams.orderbook import OrderbookSnapshot, OrderbookUpdate
from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, detached_books

from ..core import Shared, wrap_exceptions

BOOK_LIMIT = 250
"""Most levels per side `markets.orderbook` serves (its documented `limit` cap)."""


def entries(rows: Sequence[PriceLevel] | Sequence[BookLevel]) -> list[Book.Entry]:
  """Book entries from aggregated price levels."""
  return [Book.Entry(r['price'], r['quantity']) for r in rows]


def frame_book(frame: OrderbookSnapshot | OrderbookUpdate) -> Book:
  """A snapshot frame as a full book, or an update as the levels it changes.

  An update's `quantity` is the level's absolute size, `0` deleting it.
  """
  data = frame['data']
  return Book(
    bids=entries(data['bids']),
    asks=entries(data['asks']),
    time=frame['worker_timestamp'],
  )


async def depth(shared: Shared, market_id: int, *, levels: int | None = None) -> Book:
  """The aggregated REST book, best first, at most 250 levels per side, unstamped.

  Args:
    shared: The owner of the client.
    market_id: The venue's market id.
    levels: Keep at most this many levels per side.
  """
  await shared.market(market_id)
  limit = BOOK_LIMIT if levels is None else max(1, min(levels, BOOK_LIMIT))
  raw = await shared.call(
    lambda: shared.client.markets.orderbook(market_id=market_id, limit=limit)
  )
  book = Book(bids=entries(raw['bids']), asks=entries(raw['asks']))
  return book if levels is None else book.limit(levels)


def subscription(shared: Shared, market_id: int) -> Subscription[Book]:
  """One upstream book per market, on its own connection, maintained from the
  venue's snapshot and per-block level updates."""
  if market_id not in shared.books:

    @wrap_exceptions
    async def connect() -> Subscription.Context[Book]:
      """Open a dedicated client and subscribe; the snapshot precedes the ack."""
      stack = AsyncExitStack()
      own = await stack.enter_async_context(shared.public_client())
      try:
        stream = await own.streams.orderbook([market_id])
      except BaseException:
        await stack.aclose()
        raise

      @wrap_exceptions
      async def books() -> AsyncIterator[Book]:
        """Apply each frame: a snapshot replaces the book, an update patches it."""
        book: Book | None = None
        async for frame in stream:
          if frame['type'] == 'snapshot':
            book = frame_book(frame)
          elif book is None:
            continue
          else:
            book.update(frame_book(frame))
          yield book.frozen()

      @wrap_exceptions
      async def close():
        """Unsubscribe, then close the dedicated client."""
        try:
          await stream.unsubscribe()
        finally:
          await stack.aclose()

      return Subscription.Context(books(), close)

    shared.books[market_id] = Subscription(connect)
  return shared.books[market_id]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  market_id: int,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`.

  Args:
    shared: The owner of the fan-outs.
    market_id: The venue's market id.
    levels: Keep at most this many levels per side.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  await shared.market(market_id)
  upstream = subscription(shared, market_id)
  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield detached_books(stream, levels)
