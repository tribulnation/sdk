from decimal import Decimal

from tribulnation.sdk.core import Stream
from tribulnation.sdk.market import Book

from tribulnation.dydx.core import wrap_exceptions
from dydx import Indexer
from dydx.indexer.data.get_order_book import OrderBook
from dydx.indexer.streams.orders import Notification as BookUpdate

def parse_update(update: BookUpdate) -> Book:
  return Book(
    asks=[Book.Entry(price, qty) for price, qty in update.get('asks', [])],
    bids=[Book.Entry(price, qty) for price, qty in update.get('bids', [])],
  )

def parse_book(book: OrderBook) -> Book:
  return Book(
    asks=[Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size'])) for level in book['asks']],
    bids=[Book.Entry(price=Decimal(level['price']), qty=Decimal(level['size'])) for level in book['bids']],
  )

@wrap_exceptions
async def depth_stream(indexer: Indexer, market: str) -> Stream[Book]:
  stream = await indexer.streams.orders(id=market)
  book = parse_book(stream.reply)
  async def parsed_stream():
    async for msg in stream:
      book.update(parse_update(msg))
      yield book
  return Stream(parsed_stream(), stream.unsubscribe)
