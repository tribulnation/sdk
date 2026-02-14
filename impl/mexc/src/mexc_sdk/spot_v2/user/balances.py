from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market_v2.user import Balances as _Balances

from mexc_sdk.core import SpotMixin, wrap_exceptions

@dataclass
class Balances(SpotMixin, _Balances):
  @wrap_exceptions
  async def quote(self) -> _Balances.Balance:
    r = await self.client.spot.account(recvWindow=self.recvWindow)
    for b in r['balances']:
      if b['asset'] == self.info['quoteAsset']:
        return _Balances.Balance(
          free=Decimal(b['free']),
          locked=Decimal(b['locked'])
        )
    return _Balances.Balance()
    