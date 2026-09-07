"""Order book reads for one Advanced Trade product."""

from typing_extensions import AsyncIterable
from contextlib import asynccontextmanager

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Book

from tribulnation.coinbase.core import wrap_exceptions
from .mixin import MarketMixin


@wrap_exceptions
async def depth(self: MarketMixin, *, levels: int | None = None) -> Book:
  """Fetch the product's order book.

  The public pricebook serves perpetuals as well as spot, and needs no credentials.
  """
  raw = await self.app.advanced_trade.http.products.public.book(
    self.product_id, limit=levels
  )
  book = raw['pricebook']
  return Book(
    bids=[Book.Entry(price=e['price'], qty=e['size']) for e in book['bids']],
    asks=[Book.Entry(price=e['price'], qty=e['size']) for e in book['asks']],
  )


@asynccontextmanager
async def depth_stream(
  self: MarketMixin,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Subscribe to the product's order book over the `level2` channel."""
  async with self.subscribe_book(
    self.product_id, queue_size=queue_size, overflow=overflow
  ) as books:

    async def stream() -> AsyncIterable[Book]:
      async for book in books:
        yield book if levels is None else book.limit(levels)

    yield stream()
