from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.data import Depth as _Depth

from mexc_sdk.core import SpotMixin, wrap_exceptions

@dataclass
class Depth(SpotMixin, _Depth):
  @wrap_exceptions
  async def __call__(self, *, limit: int | None = None) -> _Depth.Book:
    r = await self.client.spot.depth(self.instrument, limit=limit)
    return _Depth.Book(
      asks=[_Depth.Book.Entry(
        price=Decimal(p.price),
        qty=Decimal(p.qty)
      ) for p in r['asks'][:limit]],
      bids=[_Depth.Book.Entry(
        price=Decimal(p.price),
        qty=Decimal(p.qty)
      ) for p in r['bids'][:limit]],
    )