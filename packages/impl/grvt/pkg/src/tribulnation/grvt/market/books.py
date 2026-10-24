"""Order books: REST snapshots at the smallest venue depth covering the request, and one
shared delta stream per instrument maintaining the full book."""

from contextlib import asynccontextmanager

from typing_extensions import AsyncIterator, Literal, Sequence
from typed_grvt.schemas import OrderbookLevel, OrderbookLevels
from tribulnation.sdk.core import OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, detached_books

from ..core import Shared, wrap_exceptions

Depth = Literal[10, 50, 100, 500]
DEPTHS: tuple[Depth, ...] = (10, 50, 100, 500)
"""Levels per side `orderbook` serves; 500 covers every book sampled whole."""
STREAM_RATE = 50
"""Milliseconds between `v1.book.d` deltas, the fastest the venue publishes."""


def venue_depth(levels: int | None) -> Depth:
  """The smallest venue depth covering `levels`, else the largest."""
  for depth in DEPTHS:
    if levels is not None and depth >= levels:
      return depth
  return DEPTHS[-1]


def entries(levels: Sequence[OrderbookLevel]) -> list[Book.Entry]:
  """Book entries from venue levels."""
  return [Book.Entry(level['price'], level['size']) for level in levels]


def parse_book(raw: OrderbookLevels) -> Book:
  """A book, or a delta of one, timed by its `event_time`."""
  return Book(
    bids=entries(raw['bids']), asks=entries(raw['asks']), time=raw['event_time']
  )


async def depth(shared: Shared, instrument: str, *, levels: int | None = None) -> Book:
  """The aggregated book at the smallest venue depth covering `levels`.

  Args:
    shared: The owner of the client.
    instrument: The instrument name.
    levels: Keep at most this many levels per side.
  """
  depth = venue_depth(levels)
  raw = await shared.call(
    lambda: shared.client.market.orderbook(instrument, depth=depth)
  )
  book = parse_book(raw)
  return book if levels is None else book.limit(levels)


def subscription(shared: Shared, instrument: str) -> Subscription[Book]:
  """One upstream `v1.book.d` feed per instrument, maintaining the full local book.

  The venue sends the whole book on subscribe (`num_snapshots` frames), then changed
  levels, a zero size deleting one. The client checks the sequence numbers itself and
  ends the stream with `NetworkError` on a gap, so frames are only applied here.
  """
  if instrument not in shared.books:

    @wrap_exceptions
    async def connect() -> Subscription.Context[Book]:
      """Subscribe; books are yielded once the snapshot is complete."""
      stream = await shared.client.market_streams.orderbook_delta(
        instrument, rate=STREAM_RATE
      )
      counts = stream.reply['num_snapshots']
      snapshots = counts[0] if counts else 1

      @wrap_exceptions
      async def books() -> AsyncIterator[Book]:
        """Apply each frame, after the first, to the book the first one starts."""
        book = Book()
        received = 0
        async for frame in stream:
          update = parse_book(frame)
          if received == 0:
            book = update
          else:
            book.update(update)
          received += 1
          if received >= snapshots:
            yield book.frozen()

      return Subscription.Context(books(), wrap_exceptions(stream.unsubscribe))

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
    shared: The owner of the client and its fan-outs.
    instrument: The instrument name.
    levels: Keep at most this many levels per side.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  upstream = subscription(shared, instrument)

  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield detached_books(stream, levels)
