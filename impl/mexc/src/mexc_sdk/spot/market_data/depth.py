from dataclasses import dataclass
from decimal import Decimal

from sdk.market.market_data.depth import Depth as _Depth, Book

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class Depth(_Depth, MarketMixin):
  @wrap_exceptions
  async def depth(self, *, limit: int | None = None) -> Book:
    r = await self.client.spot.depth(self.instrument, limit=limit)
    return Book(
      asks=[Book.Entry(
        price=Decimal(p.price),
        qty=Decimal(p.qty)
      ) for p in r['asks'][:limit]],
      bids=[Book.Entry(
        price=Decimal(p.price),
        qty=Decimal(p.qty)
      ) for p in r['bids'][:limit]],
    )
