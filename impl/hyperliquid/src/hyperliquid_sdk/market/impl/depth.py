from decimal import Decimal

from trading_sdk.core import Stream
from trading_sdk.market import Book

from hyperliquid_sdk.core import wrap_exceptions


@wrap_exceptions
async def depth(self) -> Book:
  book = await self.client.info.l2_book(self.asset_name)
  raw_bids, raw_asks = book["levels"]
  bids = [Book.Entry(price=Decimal(b["px"]), qty=Decimal(b["sz"])) for b in raw_bids]
  asks = [Book.Entry(price=Decimal(a["px"]), qty=Decimal(a["sz"])) for a in raw_asks]
  return Book(
    bids=sorted(bids, key=lambda e: e.price, reverse=True),
    asks=sorted(asks, key=lambda e: e.price),
  )


async def depth_stream(self) -> Stream[Book]:
  l2 = await self.subscribe_l2_book(self.asset_name)

  async def stream():
    async for update in l2:
      raw_bids, raw_asks = update["levels"]
      # Hyperliquid `l2Book` is a snapshot-per-message feed.
      book = Book(
        bids=sorted(
          [Book.Entry(price=Decimal(b["px"]), qty=Decimal(b["sz"])) for b in raw_bids],
          key=lambda e: e.price,
          reverse=True,
        ),
        asks=sorted(
          [Book.Entry(price=Decimal(a["px"]), qty=Decimal(a["sz"])) for a in raw_asks],
          key=lambda e: e.price,
        ),
      )
      yield book

  return Stream(stream(), l2.unsubscribe)

