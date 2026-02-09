from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.market_data.depth import Depth as _Depth, Book

from dydx_sdk.core import MarketMixin, MarketDataMixin, wrap_exceptions, perp_name

@dataclass
class Depth(MarketDataMixin, MarketMixin, _Depth):
  @wrap_exceptions
  async def depth(self, *, limit: int | None = None) -> Book:
    book = await self.indexer_data.get_order_book(self.market, unsafe=True)
    return Book(
      asks=[Book.Entry(
        price=Decimal(p['price']),
        qty=Decimal(p['size'])
      ) for p in book['asks'][:limit]],
      bids=[Book.Entry(
        price=Decimal(p['price']),
        qty=Decimal(p['size'])
      ) for p in book['bids'][:limit]],
    )
    