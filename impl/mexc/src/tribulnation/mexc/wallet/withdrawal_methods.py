from typing_extensions import Sequence
from decimal import Decimal

from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod, WithdrawalMethods as _WithdrawalMethods

from tribulnation.mexc.core import Mixin, wrap_exceptions

class WithdrawalMethods(Mixin, _WithdrawalMethods):
  @wrap_exceptions
  async def withdrawal_methods(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[str] | None = None
  ) -> Sequence[WithdrawalMethod]:
    currencies = await self.client.spot.wallet.currency_info()

    out: list[WithdrawalMethod] = []
    for c in currencies:
      asset = c.get('coin')
      if asset is None or (assets is not None and asset not in assets):
        continue
      for m in c.get('networkList', []):
        network = m.get('netWork') or m.get('network')
        if not m.get('withdrawEnable') or network is None:
          continue
        if networks is not None and network not in networks:
          continue
        out.append(WithdrawalMethod(
          network=network,
          contract_address=m.get('contract'),
          asset=asset,
          fee=WithdrawalMethod.Fee(
            asset=asset,
            amount=Decimal(m.get('withdrawFee') or '0'),
          ),
        ))

    return out
