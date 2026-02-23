from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.data import Index as _Index
from dydx_sdk.core import MarketMixin, wrap_exceptions

@dataclass(frozen=True)
class Index(MarketMixin, _Index):
  @wrap_exceptions
  async def price(self):
    market = await self.indexer.data.get_market(self.market)
    return Decimal(market['oraclePrice'])