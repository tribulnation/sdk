from dataclasses import dataclass

from tribulnation.sdk.market.data import Depth as _Depth

from mexc_sdk.core import MarketMixin

@dataclass
class Depth(MarketMixin, _Depth):
  async def book(self, *, limit: int | None = None) -> _Depth.Book:
    raise NotImplementedError('MEXC futures order book is not implemented')
