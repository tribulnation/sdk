from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.wallet.withdrawal_methods import WithdrawalMethod, WithdrawalMethods as _WithdrawalMethods

from mexc_sdk.core import SdkMixin, wrap_exceptions

@dataclass
class WithdrawalMethods(SdkMixin, _WithdrawalMethods):
  @wrap_exceptions
  async def withdrawal_methods(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[str] | None = None
  ) -> Sequence[WithdrawalMethod]:
    currencies = await self.client.spot.currency_info()

    out: list[WithdrawalMethod] = []
    for c in currencies:
      if assets is None or c['coin'] in assets:
        for m in c['networkList']:
          if m['withdrawEnable'] and (networks is None or m['netWork'] in networks):
            out.append(WithdrawalMethod(
              network=m['netWork'],
              contract_address=m.get('contract'),
              asset=c['coin'],
              fee=WithdrawalMethod.Fee(
                asset=c['coin'],
                amount=Decimal(m['withdrawFee']),
              ),
            ))

    return out