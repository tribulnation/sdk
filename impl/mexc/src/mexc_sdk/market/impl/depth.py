from decimal import Decimal

from trading_sdk.core import Stream
from trading_sdk.market import Book

from mexc_sdk.core.exc import wrap_exceptions
from .mixin import MarketMixin


@wrap_exceptions
async def depth(self: MarketMixin, *, levels: int | None = None) -> Book:
  r = await self.client.spot.depth(self.instrument, validate=self.shared.validate, limit=levels)
  return Book(
    asks=[Book.Entry(price=Decimal(p.price), qty=Decimal(p.qty)) for p in r["asks"]],
    bids=[Book.Entry(price=Decimal(p.price), qty=Decimal(p.qty)) for p in r["bids"]],
  )


async def depth_stream(self: MarketMixin, *, levels: int | None = None) -> Stream[Book]:
  stream = await self.subscribe_depth(levels=levels)

  async def gen():
    async for msg in stream:
      book = Book(
        asks=[Book.Entry(price=Decimal(a.price), qty=Decimal(a.quantity)) for a in msg.asks],
        bids=[Book.Entry(price=Decimal(b.price), qty=Decimal(b.quantity)) for b in msg.bids],
      )
      yield book

  return Stream(gen(), stream.unsubscribe)

