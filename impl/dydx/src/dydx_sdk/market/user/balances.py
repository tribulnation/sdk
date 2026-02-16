from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import Balances as _Balances
from dydx_sdk.core import MarketMixin, IndexerDataMixin, SubaccountMixin, wrap_exceptions

@dataclass
class Balances(MarketMixin, IndexerDataMixin, SubaccountMixin, _Balances):
  @wrap_exceptions
  async def quote(self) -> _Balances.Balance:
    subaccount = await self.indexer_data.get_subaccount(self.address)
    free = Decimal(subaccount['freeCollateral'])
    total = Decimal(subaccount['equity'])
    return _Balances.Balance(free=free, locked=total - free)