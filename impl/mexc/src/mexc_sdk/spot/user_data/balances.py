from typing_extensions import Mapping
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.user_data.balance import Balances as _Balances, Balance

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class Balances(MarketMixin, _Balances):
  @wrap_exceptions
  async def _balances_impl(self, *currencies: str) -> Mapping[str, Balance]:
    r = await self.client.spot.account(recvWindow=self.recvWindow)
    return {
      b['asset']: Balance(
        free=Decimal(b['free']),
        locked=Decimal(b['locked'])
      )
      for b in r['balances']
    }

  async def balance(self, currency: str, /) -> Balance:
    return await super().balance(currency)
    