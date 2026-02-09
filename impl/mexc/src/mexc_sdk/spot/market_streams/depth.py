from typing_extensions import Literal
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.market_streams.depth import Depth as _Depth, Book
from mexc_sdk.core import MarketMixin, wrap_exceptions

def level(limit: int | None) -> Literal[5, 10, 20]:
  if limit is None:
    return 20
  elif limit < 5:
    return 5
  elif limit < 10:
    return 10
  else:
    return 20

@dataclass
class Depth(MarketMixin, _Depth):
  @wrap_exceptions
  async def depth_stream(self, *, limit: int | None = None):
    async for book in self.client.spot.streams.depth(self.instrument, level(limit)):
      yield Book(
        bids=[Book.Entry(price=Decimal(e.price), qty=Decimal(e.qty)) for e in book.bids],
        asks=[Book.Entry(price=Decimal(e.price), qty=Decimal(e.qty)) for e in book.asks]
      )
