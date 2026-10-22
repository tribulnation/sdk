"""Order books: REST snapshots, the RFQ quotes stream, and one shared WS book per market.

An RFQ market's REST and `orderbooks` books are the venue's indicative book; its real
book is the quotes, which the venue publishes on the `orderbooks/rfq` stream only.
"""

from contextlib import asynccontextmanager

from typing_extensions import Any, AsyncIterable, AsyncIterator, Sequence
from typed_core.util import StreamManager
from typed_extended.info.schemas import OrderbookLevel
from typed_extended.streams.schemas import OrderbookMessage, StreamOrderbookLevel
from tribulnation.sdk.core import (
  ApiError,
  MissingData,
  NetworkError,
  OverflowPolicy,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book

from ..core import Shared


def book_entries(rows: Sequence[OrderbookLevel]) -> list[Book.Entry]:
  """Book entries from REST price levels."""
  return [Book.Entry(r['price'], r['qty']) for r in rows]


def snapshot_entries(rows: Sequence[StreamOrderbookLevel]) -> list[Book.Entry]:
  """Book entries from a stream snapshot, whose `q` is the absolute size."""
  return [Book.Entry(r['p'], r['q']) for r in rows]


def delta_entries(rows: Sequence[StreamOrderbookLevel]) -> list[Book.Entry]:
  """Book entries from a delta, at their absolute size `c` (`0` deletes the level).

  Raises:
    ApiError: A delta level carries no absolute size.
  """
  entries: list[Book.Entry] = []
  for r in rows:
    size = r.get('c')
    if size is None:
      raise ApiError(f'Extended book delta without its absolute size: {r}')
    entries.append(Book.Entry(r['p'], size))
  return entries


def frame_book(frame: OrderbookMessage) -> Book:
  """A snapshot frame as a full book, or a delta frame as the levels it changes."""
  data = frame['data']
  if frame['type'] == 'SNAPSHOT':
    return Book(
      bids=snapshot_entries(data['b']),
      asks=snapshot_entries(data['a']),
      time=frame['ts'],
    )
  return Book(
    bids=delta_entries(data['b']), asks=delta_entries(data['a']), time=frame['ts']
  )


def frozen(book: Book) -> Book:
  """This frame's book, unaffected by later frames.

  `Book.update` rebinds new level lists and never mutates an entry, so sharing the
  entries is safe and costs no copy of a book thousands of levels deep (a deep copy of
  BTC-USD's ~7000 levels takes longer than the 100 ms between deltas).
  """
  return Book(bids=list(book.bids), asks=list(book.asks), time=book.time)


def detached(book: Book, levels: int | None = None) -> Book:
  """A subscriber's own book, trimmed to `levels`, with fresh entries it may mutate."""
  bids = book.bids if levels is None else book.bids[:levels]
  asks = book.asks if levels is None else book.asks[:levels]
  return Book(
    bids=[Book.Entry(e.price, e.qty) for e in bids],
    asks=[Book.Entry(e.price, e.qty) for e in asks],
    time=book.time,
  )


def book_stream(
  shared: Shared, market: str, *, rfq: bool
) -> StreamManager[OrderbookMessage, Any, Any]:
  """The market's book stream: the quotes on an RFQ market, else the full book."""
  if rfq:
    return shared.client.streams.rfq_orderbooks(market)
  return shared.client.streams.orderbooks(market)


async def read_quotes(shared: Shared, market: str) -> Book:
  """The first snapshot of an RFQ market's quotes stream, stamped with its `ts`.

  Raises:
    NetworkError: The stream closed before its snapshot.
  """
  async with book_stream(shared, market, rfq=True) as stream:
    async for frame in stream:
      if frame['type'] == 'SNAPSHOT':
        return frame_book(frame)
  raise NetworkError(f'Extended {market} quotes stream closed before its snapshot')


async def depth(shared: Shared, market: str, *, levels: int | None = None) -> Book:
  """The whole aggregated REST book (no timestamp), or an RFQ market's quotes.

  Args:
    shared: The owner of the client.
    market: The market name.
    levels: Keep at most this many levels per side.

  Raises:
    MissingData: The venue has no book for the market (inactive or unknown).
  """
  if (await shared.perp(market))['isRfq']:
    book = await shared.call(lambda: read_quotes(shared, market))
  else:
    raw = await shared.call(lambda: shared.client.info.orderbook(market))
    if raw is None:
      raise MissingData(
        f'Extended has no order book for {market} (inactive or unknown market)',
        market_id=market,
        field='depth',
      )
    book = Book(bids=book_entries(raw['bid']), asks=book_entries(raw['ask']))
  return book if levels is None else book.limit(levels)


def subscription(shared: Shared, market: str, *, rfq: bool) -> Subscription[Book]:
  """One upstream book per market, maintained from snapshots and deltas."""
  if market not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Subscribe; the venue sends a snapshot, then deltas and a fresh snapshot a minute."""
      stream = await book_stream(shared, market, rfq=rfq)

      @exception_wrapper()
      async def books() -> AsyncIterator[Book]:
        """Apply each frame, failing on a `seq` gap (a missed update)."""
        book = Book()
        seq: int | None = None
        async for frame in stream:
          if seq is not None and frame['seq'] != seq + 1:
            raise NetworkError(
              f'Extended order book {market} skipped updates: {seq} -> {frame["seq"]}'
            )
          seq = frame['seq']
          if frame['type'] == 'SNAPSHOT':
            book = frame_book(frame)
          else:
            book.update(frame_book(frame))
          yield frozen(book)

      return Subscription.Context(books(), exception_wrapper()(stream.unsubscribe))

    shared.books[market] = Subscription(connect)
  return shared.books[market]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  market: str,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`.

  Args:
    shared: The owner of the client and its fan-outs.
    market: The market name; an RFQ market's book is its quotes.
    levels: Keep at most this many levels per side.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  rfq = (await shared.perp(market))['isRfq']
  upstream = subscription(shared, market, rfq=rfq)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Detach before handing out: subscribers share each upstream book."""
    async for book in books:
      yield detached(book, levels)

  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
