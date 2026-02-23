from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Index as _Index

from mexc_sdk.core import PerpMixin, wrap_exceptions

@dataclass(frozen=True)
class Index(PerpMixin, _Index):
  @wrap_exceptions
  async def price(self) -> Decimal:
    r = await self.client.futures.depth(self.instrument, limit=1)
    best_bid = Decimal(r['bids'][0].price)
    best_ask = Decimal(r['asks'][0].price)
    return (best_bid + best_ask) / Decimal(2)
