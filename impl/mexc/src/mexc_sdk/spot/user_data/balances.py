from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_data.balances import Balances as _Balances, Balance

from mexc_sdk.core import SdkMixin, wrap_exceptions

@dataclass
class Balances(SdkMixin, _Balances):
  @wrap_exceptions
  async def _balances_impl(self, *currencies: str) -> dict[str, Balance]:
    r = await self.client.spot.account(recvWindow=self.recvWindow)
    return {
      b['asset']: Balance(
        free=Decimal(b['free']),
        locked=Decimal(b['locked'])
      )
      for b in r['balances']
    }
    