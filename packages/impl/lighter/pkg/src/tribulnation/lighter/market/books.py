"""Order books: REST snapshots aggregated from resting orders, and a shared WS book."""

from contextlib import asynccontextmanager
from decimal import Decimal

from typing_extensions import AsyncIterable, AsyncIterator, Sequence
from typed_lighter.schemas import PriceLevel, SimpleOrder
from tribulnation.sdk.core import (
  NetworkError,
  OverflowPolicy,
  Subscription,
  exception_wrapper,
)
from tribulnation.sdk.market import Book

from ..core import Shared

BOOK_ORDERS_LIMIT = 250
"""Most resting orders per side `orderBookOrders` returns (251 is rejected)."""


def aggregate(orders: Sequence[SimpleOrder], *, full: bool) -> list[Book.Entry]:
  """Sum orders into price levels, best first. A full side's last level may be
  missing orders beyond the limit, so it is dropped rather than reported short."""
  levels: dict[Decimal, Decimal] = {}
  for o in orders:
    levels[o['price']] = levels.get(o['price'], Decimal(0)) + o['remaining_base_amount']
  entries = [Book.Entry(price, qty) for price, qty in levels.items()]
  return entries[:-1] if full else entries


async def depth(shared: Shared, market_id: int, *, levels: int | None = None) -> Book:
  """The book from the top resting orders of each side (at most 250 per side)."""
  raw = await shared.call(
    lambda: shared.client.api.markets.order_book_orders(
      market_id=market_id, limit=BOOK_ORDERS_LIMIT
    )
  )
  book = Book(
    bids=aggregate(raw['bids'], full=raw['total_bids'] == BOOK_ORDERS_LIMIT),
    asks=aggregate(raw['asks'], full=raw['total_asks'] == BOOK_ORDERS_LIMIT),
  )
  return book if levels is None else book.limit(levels)


def levels_of(rows: Sequence[PriceLevel]) -> list[Book.Entry]:
  """Book entries from venue price levels."""
  return [Book.Entry(r['price'], r['size']) for r in rows]


def subscription(shared: Shared, market_id: int) -> Subscription[Book]:
  """One upstream `order_book` feed per market, maintaining the full local book."""
  if market_id not in shared.books:

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
          delta = Book(bids=levels_of(state['bids']), asks=levels_of(state['asks']))
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
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`."""
  source = subscription(shared, market_id)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Copy before handing out: subscribers share each upstream snapshot."""
    async for book in books:
      yield book.copy() if levels is None else book.copy().limit(levels)

  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
