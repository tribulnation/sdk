from typing_extensions import Awaitable, Callable
from decimal import Decimal

from tribulnation.sdk.market import Book

from tribulnation.dydx.core import wrap_exceptions
from typed_dydx import Indexer
from typed_dydx.indexer.schemas import OrderBook
from typed_dydx.indexer.streams.orders import OrderbookMessageContents as BookUpdate

from .reconnect import Opened, reconnecting


def parse_update(update: BookUpdate) -> Book:
  return Book(
    asks=[Book.Entry(price, qty) for price, qty in update.get('asks', [])],
    bids=[Book.Entry(price, qty) for price, qty in update.get('bids', [])],
  )


def parse_book(book: OrderBook) -> Book:
  # dYdX's Indexer exposes no book timestamp (REST or WS), so `time` stays None.
  return Book(
    asks=[
      Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size']))
      for level in book['asks']
    ],
    bids=[
      Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size']))
      for level in book['bids']
    ],
  )


def depth_stream(
  indexer: Indexer, market: str
) -> Callable[[], Awaitable[Opened[Book]]]:
  """A `Subscription.of` callback for a market's book that reconnects
  (`reconnecting`). After a reconnection the new subscription's snapshot comes first,
  so subscribers never keep a book that missed updates."""

  @wrap_exceptions
  async def open(reopen: bool) -> Opened[Book]:
    """Subscribe; the book starts from the subscription's snapshot."""
    stream = await indexer.streams.orders(id=market)
    book = parse_book(stream.reply)

    @wrap_exceptions
    async def parsed_stream():
      """The book after each update, the snapshot first after a reconnection."""
      if reopen:
        yield book
      async for msg in stream:
        book.update(parse_update(msg))
        yield book

    return parsed_stream(), stream.unsubscribe

  return reconnecting(f'book {market}', open)
