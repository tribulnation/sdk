from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Depth as _Depth
from dydx_sdk.core import Mixin, wrap_exceptions

@dataclass
class Depth(Mixin, _Depth):
  @wrap_exceptions
  async def book(self, *, limit: int | None = None) -> _Depth.Book:
    book = await self.indexer.data.get_order_book(self.market)
    return _Depth.Book(
      asks=[_Depth.Book.Entry(
        price=Decimal(p['price']),
        qty=Decimal(p['size'])
      ) for p in book['asks'][:limit]],
      bids=[_Depth.Book.Entry(
        price=Decimal(p['price']),
        qty=Decimal(p['size'])
      ) for p in book['bids'][:limit]],
    )