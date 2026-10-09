"""Order books: REST snapshots aggregated from resting orders, and shared WS books per
`depth_source` (the full `order_book`, or the `ticker` best bid/offer)."""

from contextlib import asynccontextmanager
from decimal import Decimal

from typing_extensions import AsyncIterable, AsyncIterator, Mapping, Sequence
from typed_lighter.core import timestamp_micros
from typed_lighter.schemas import PriceLevel, SimpleOrder
from typed_lighter.streams.ticker import TickerUpdate
from tribulnation.sdk.core import (
  NetworkError,
  OverflowPolicy,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book, Settings
from tribulnation.sdk.util import epoch_time

from ..core import DepthSource, Shared

BOOK_ORDERS_LIMIT = 250
"""Most resting orders per side `orderBookOrders` returns (251 is rejected)."""
SOURCE_LEVELS: Mapping[DepthSource, int | None] = {'order_book': None, 'bbo': 1}
"""Levels per side each source delivers (`None`: the full book); REST `depth` trims to
the same shape."""


def depth_source(settings: Settings) -> DepthSource:
  """The `lighter.depth_source` setting, defaulting to `'order_book'`.

  Args:
    settings: Venue-keyed settings; only the `lighter` key is read.

  Raises:
    ValueError: The setting names no known source.
  """
  source = settings.get('lighter', {}).get('depth_source', 'order_book')
  if source not in SOURCE_LEVELS:
    raise ValueError(
      f'Unknown Lighter depth_source {source!r}; expected one of {list(SOURCE_LEVELS)}'
    )
  return source


def cap_levels(source: DepthSource, levels: int | None) -> int | None:
  """The levels per side to keep: the caller's `levels`, capped at the source's shape.

  Args:
    source: The selected depth source.
    levels: The caller's requested cap, if any.
  """
  limit = SOURCE_LEVELS[source]
  if limit is None:
    return levels
  return limit if levels is None else min(levels, limit)


def aggregate(orders: Sequence[SimpleOrder], *, full: bool) -> list[Book.Entry]:
  """Sum orders into price levels, best first. A full side's last level may be
  missing orders beyond the limit, so it is dropped rather than reported short."""
  levels: dict[Decimal, Decimal] = {}
  for o in orders:
    levels[o['price']] = levels.get(o['price'], Decimal(0)) + o['remaining_base_amount']
  entries = [Book.Entry(price, qty) for price, qty in levels.items()]
  return entries[:-1] if full else entries


async def depth(
  shared: Shared,
  market_id: int,
  *,
  levels: int | None = None,
  source: DepthSource = 'order_book',
) -> Book:
  """The book from the top resting orders of each side (at most 250 per side).

  Args:
    shared: The owner of the client.
    market_id: The venue's market id.
    levels: Keep at most this many levels per side.
    source: The depth source whose shape to match: `'bbo'` trims to 1 level per side.
  """
  levels = cap_levels(source, levels)
  raw = await shared.call(
    lambda: shared.client.api.markets.order_book_orders(
      market_id=market_id, limit=BOOK_ORDERS_LIMIT
    )
  )
  # `orderBookOrders` carries no snapshot timestamp, so `time` stays None.
  book = Book(
    bids=aggregate(raw['bids'], full=raw['total_bids'] == BOOK_ORDERS_LIMIT),
    asks=aggregate(raw['asks'], full=raw['total_asks'] == BOOK_ORDERS_LIMIT),
  )
  return book if levels is None else book.limit(levels)


def levels_of(rows: Sequence[PriceLevel]) -> list[Book.Entry]:
  """Book entries from venue price levels."""
  return [Book.Entry(r['price'], r['size']) for r in rows]


def parse_ticker(frame: TickerUpdate) -> Book:
  """Convert a `ticker` frame into a one-level book, timed by its `last_updated_at`.

  `last_updated_at` is the time of the book change the best bid/offer belongs to, the
  same clock as `order_book`'s, so books from both sources compare; the frame's send
  `timestamp` is not used. A side with a zero price or size (an empty side) becomes
  an empty list.
  """
  ticker = frame['ticker']
  bid, ask = ticker['b'], ticker['a']
  bids = [Book.Entry(Decimal(bid['price']), Decimal(bid['size']))]
  asks = [Book.Entry(Decimal(ask['price']), Decimal(ask['size']))]
  return Book(
    bids=[e for e in bids if e.price > 0 and e.qty > 0],
    asks=[e for e in asks if e.price > 0 and e.qty > 0],
    time=epoch_time(ticker['last_updated_at'], timestamp_micros),
  )


def ticker_subscription(shared: Shared, market_id: int) -> Subscription[Book]:
  """One upstream `ticker` feed per market; every frame is a full best bid/offer."""
  key = (market_id, 'bbo')
  if key not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Subscribe; each frame replaces the previous one."""
      stream = await shared.client.streams.ticker(market_id)

      @exception_wrapper()
      async def books() -> AsyncIterator[Book]:
        """Parse each frame; no chain to verify, since nothing is applied as a diff."""
        async for frame in stream:
          yield parse_ticker(frame)

      return Subscription.Context(books(), exception_wrapper()(stream.unsubscribe))

    shared.books[key] = Subscription(connect)
  return shared.books[key]


def order_book_subscription(shared: Shared, market_id: int) -> Subscription[Book]:
  """One upstream `order_book` feed per market, maintaining the full local book."""
  key = (market_id, 'order_book')
  if key not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Subscribe; the first frame is the full book, later ones changed levels."""
      stream = await shared.client.streams.order_book(market_id)

      @exception_wrapper()
      async def books() -> AsyncIterator[Book]:
        """Apply each delta, failing on a nonce gap (a missed update)."""
        book = Book()
        nonce: int | None = None
        async for frame in stream:
          state = frame['order_book']
          delta = Book(
            bids=levels_of(state['bids']),
            asks=levels_of(state['asks']),
            time=epoch_time(state['last_updated_at'], timestamp_micros),
          )
          if frame['type'] == 'subscribed/order_book':
            book = delta
          elif nonce is not None and state['begin_nonce'] != nonce:
            raise NetworkError(
              f'Lighter order book {market_id} skipped updates: '
              f'{nonce} -> {state["begin_nonce"]}'
            )
          else:
            book.update(delta)
          nonce = state['nonce']
          yield book.copy()

      return Subscription.Context(books(), exception_wrapper()(stream.unsubscribe))

    shared.books[key] = Subscription(connect)
  return shared.books[key]


def subscription(
  shared: Shared, market_id: int, source: DepthSource = 'order_book'
) -> Subscription[Book]:
  """The shared upstream of one market and depth source.

  Args:
    shared: The owner of the client and its fan-outs.
    market_id: The venue's market id.
    source: Which channel to read.
  """
  if source == 'bbo':
    return ticker_subscription(shared, market_id)
  return order_book_subscription(shared, market_id)


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  market_id: int,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
  source: DepthSource = 'order_book',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`.

  Args:
    shared: The owner of the client and its fan-outs.
    market_id: The venue's market id.
    levels: Keep at most this many levels per side; it never selects the source.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
    source: Which channel to read; consumers of one market and source share it.
  """
  upstream = subscription(shared, market_id, source)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Copy before handing out: subscribers share each upstream snapshot."""
    async for book in books:
      yield book.copy() if levels is None else book.copy().limit(levels)

  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
