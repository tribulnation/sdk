from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Depth as _Depth

from mexc_sdk.core import PerpMixin, wrap_exceptions

@dataclass(frozen=True)
class Depth(PerpMixin, _Depth):
  @wrap_exceptions
  async def book(self, *, limit: int | None = None) -> _Depth.Book:
    contract_size = Decimal(self.info['contractSize'])

    r = await self.client.futures.depth(self.instrument, limit=limit)
    asks = [
      _Depth.Book.Entry(price=Decimal(e.price), qty=Decimal(e.qty) * contract_size)
      for e in r['asks'][:limit]
    ]
    bids = [
      _Depth.Book.Entry(price=Decimal(e.price), qty=Decimal(e.qty) * contract_size)
      for e in r['bids'][:limit]
    ]
    return _Depth.Book(asks=asks, bids=bids)
