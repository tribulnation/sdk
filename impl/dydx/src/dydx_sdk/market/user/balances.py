from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.user import Balances as _Balances
from dydx_sdk.core import MarketMixin, wrap_exceptions

@dataclass(frozen=True)
class Balances(MarketMixin, _Balances):
  @wrap_exceptions
  async def quote(self) -> _Balances.Balance:
    subaccount = await self.indexer.data.get_subaccount(self.address)
    free = Decimal(subaccount['freeCollateral'])
    total = Decimal(subaccount['equity'])
    return _Balances.Balance(free=free, locked=total - free)