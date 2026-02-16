from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user import PerpPosition
from dydx_sdk.core import MarketMixin, IndexerDataMixin, SubaccountMixin, wrap_exceptions

@dataclass
class Position(MarketMixin, IndexerDataMixin, SubaccountMixin, PerpPosition):
  @wrap_exceptions
  async def get(self) -> PerpPosition.Position:
    position = await self.indexer_data.get_open_position(self.market, address=self.address, subaccount=self.subaccount)
    size = Decimal(position['size']) if position is not None else Decimal(0)
    entry_price = Decimal(position['entryPrice']) if position is not None else Decimal(0)
    return PerpPosition.Position(size=size, entry_price=entry_price)
