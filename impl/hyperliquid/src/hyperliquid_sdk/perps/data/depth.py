from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Depth as _Depth
from hyperliquid_sdk.perps.core import PerpMixin

@dataclass(frozen=True)
class Depth(PerpMixin, _Depth):
  async def book(self, *, limit: int | None = None) -> _Depth.Book:
    book = await self.client.info.l2_book(self.asset_name)
    raw_bids, raw_asks = book['levels']
    bids = [
      _Depth.Book.Entry(
        price=Decimal(bid['px']),
        qty=Decimal(bid['sz'])
      )
      for bid in raw_bids
    ]
    asks = [
      _Depth.Book.Entry(
        price=Decimal(ask['px']),
        qty=Decimal(ask['sz'])
      )
      for ask in raw_asks
    ]
    return _Depth.Book(
      bids=sorted(bids, key=lambda e: e.price, reverse=True),
      asks=sorted(asks, key=lambda e: e.price)
    )
  