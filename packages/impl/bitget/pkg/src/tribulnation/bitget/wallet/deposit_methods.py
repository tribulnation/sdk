from typing_extensions import Sequence, Collection
from decimal import Decimal

from tribulnation.sdk.wallet.deposit_methods import (
  DepositMethod,
  DepositMethods as _DepositMethods,
)
from tribulnation.bitget.core import SdkMixin, wrap_exceptions
from typed_bitget.classic.spot.coins import SpotCoinChain, SpotCoin


def _rechargeable(chain: SpotCoinChain) -> bool:
  return chain['rechargeable']


def _parse_coins_response_deposits(
  raw: list[SpotCoin],
  *,
  assets: Collection[str] | None = None,
) -> list[DepositMethod]:
  assets_set = set(assets) if assets is not None else None
  out: list[DepositMethod] = []
  for coin_info in raw:
    coin = coin_info['coin']
    if assets_set is not None and coin not in assets_set:
      continue
    chains = coin_info['chains']
    for ch in chains:
      if not _rechargeable(ch):
        continue
      network = ch['chain']
      fee = DepositMethod.Fee(asset=coin, amount=Decimal('0'))
      contract = ch.get('contractAddress')
      contract_address = str(contract) if contract is not None else None
      dep_confirm = ch.get('depositConfirm')
      min_confirmations: int | None = None
      if dep_confirm is not None:
        try:
          min_confirmations = int(dep_confirm)
        except (TypeError, ValueError):
          pass
      out.append(
        DepositMethod(
          asset=coin,
          network=network,
          fee=fee,
          contract_address=contract_address,
          min_confirmations=min_confirmations,
        )
      )
  return out


class DepositMethods(SdkMixin, _DepositMethods):
  @wrap_exceptions
  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    if await self.is_uta():
      raise NotImplementedError('Deposit methods are not supported in UTA mode.')
    else:
      r = await self.client.classic.spot.coins()
      return _parse_coins_response_deposits(r, assets=assets)
