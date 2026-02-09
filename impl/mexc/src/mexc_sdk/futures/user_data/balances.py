from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_data.balances import Balances as _Balances, Balance

from mexc_sdk.core import SdkMixin, wrap_exceptions

@dataclass
class Balances(SdkMixin, _Balances):
  @wrap_exceptions
  async def balances(self, *currencies: str) -> dict[str, Balance]:
    r = await self.client.futures.assets(recvWindow=self.recvWindow)
    return {
      b['currency']: Balance(
        free=Decimal(b['availableBalance']),
        locked=Decimal(b['positionMargin'])
      )
      for b in r
    }
    