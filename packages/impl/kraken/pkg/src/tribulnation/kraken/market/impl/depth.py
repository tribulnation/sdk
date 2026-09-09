"""Order book, snapshot and stream."""

from typing_extensions import TYPE_CHECKING, AsyncIterable, AsyncIterator, Literal
from contextlib import asynccontextmanager
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Book

from typed_kraken.spot.market_data.depth import OrderBook
from typed_kraken.streams.market_data.book import BookData, BookMessage

if TYPE_CHECKING:
  from .mixin import MarketMixin

BookDepth = Literal[10, 25, 100, 500, 1000]
"""The only per-side depths the `book` channel serves."""

BOOK_DEPTHS: tuple[BookDepth, ...] = (10, 25, 100, 500, 1000)


def book_depth(levels: int | None) -> BookDepth:
  """The smallest channel depth holding `levels` per side.

  The SDK asks for any number of levels; Kraken subscribes at one of five fixed
  depths. `None` takes the channel's own default of 10, and anything past 1000 is
  capped there, the deepest book the channel serves.

  Args:
    levels: Levels per side wanted, or `None` for the default.
  """
  if levels is None:
    return 10
  for depth in BOOK_DEPTHS:
    if levels <= depth:
      return depth
  return 1000


def parse_book(book: OrderBook) -> Book:
  """Map one REST `Depth` book onto a `Book`.

  Each level is `[price, volume, timestamp]`; the timestamp is dropped.
  """
  return Book(
    bids=[Book.Entry(price=p, qty=q) for p, q, _ in book.get('bids') or []],
    asks=[Book.Entry(price=p, qty=q) for p, q, _ in book.get('asks') or []],
  )


def parse_levels(data: BookData) -> Book:
  """Map one streamed push's levels onto a `Book`.

  The channel sends prices and quantities as JSON numbers, which the client keeps
  as `float`; each is transcribed through its shortest string representation.
  """
  return Book(
    bids=[
      Book.Entry(price=Decimal(str(e['price'])), qty=Decimal(str(e['qty'])))
      for e in data['bids']
    ],
    asks=[
      Book.Entry(price=Decimal(str(e['price'])), qty=Decimal(str(e['qty'])))
      for e in data['asks']
    ],
  )


async def fold_books(messages: AsyncIterable[BookMessage]) -> AsyncIterator[Book]:
  """Fold the `book` channel's snapshot-then-updates pushes into whole books.

  The channel sends one full snapshot on subscribe and then only the changed
  levels, a zero quantity meaning the level was removed -- `Book.update`'s exact
  contract. Each yielded book is a copy, so a book already handed to a subscriber is
  never mutated by a later push.
  """
  book = Book()
  async for message in messages:
    for data in message['data']:
      levels = parse_levels(data)
      if message['type'] == 'snapshot':
        book = levels
      else:
        book.update(levels)
      yield book.copy()


async def depth(self: 'MarketMixin', *, levels: int | None = None) -> Book:
  """Fetch the market order book.

  `Depth` takes `count` as the maximum levels per side and answers keyed by the
  pair's internal name, whatever spelling was asked for.
  """
  raw = await self.call_kraken(
    lambda: self.client.spot.market_data.depth(self.altname, count=levels)
  )
  return parse_book(raw[self.meta['pair']['key']])


@asynccontextmanager
async def depth_stream(
  self: 'MarketMixin',
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Subscribe to the market order book.

  The subscription is made at the smallest of Kraken's fixed depths holding
  `levels` (see `book_depth`), and each book is then trimmed to `levels` when one
  was given, so the SDK's arbitrary size is honoured exactly.
  """
  depth = book_depth(levels)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    async for book in books:
      yield book if levels is None else book.limit(levels)

  async with self.subscribe_depth(
    depth, queue_size=queue_size, overflow=overflow
  ) as stream:
    yield trimmed(stream)
