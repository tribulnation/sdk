from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user import Balances as _Balances

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class Balances(MarketMixin, _Balances):
  @wrap_exceptions
  async def quote(self) -> _Balances.Balance:
    info = await self.client.futures.contract_info(self.instrument)
    settle = info.get('settleCoin')
    if settle is None:
      return _Balances.Balance()

    r = await self.client.futures.assets(recvWindow=self.recvWindow)
    for b in r:
      if b.get('currency') == settle:
        return _Balances.Balance(
          free=Decimal(b['availableBalance']),
          locked=Decimal(b['positionMargin']),
        )
    return _Balances.Balance()
