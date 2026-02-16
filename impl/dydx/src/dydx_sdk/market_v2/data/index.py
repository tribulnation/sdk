from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market_v2.data import Index as _Index
from dydx_sdk.core import MarketMixin, IndexerDataMixin, wrap_exceptions

@dataclass
class Index(MarketMixin, IndexerDataMixin, _Index):
  @wrap_exceptions
  async def price(self):
    market = await self.indexer_data.get_market(self.market)
    return Decimal(market['oraclePrice'])