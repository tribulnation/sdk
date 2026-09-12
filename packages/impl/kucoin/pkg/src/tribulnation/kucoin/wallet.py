"""Kucoin's public currency/network deposit and withdrawal methods."""

from decimal import Decimal
from typing_extensions import Collection, Sequence
from tribulnation.sdk.wallet import Wallet as BaseWallet
from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod
from .core import Mixin


class Wallet(Mixin, BaseWallet):
  """List network methods without creating addresses or moving funds."""

  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """Keep enabled deposit chains and the venue's confirmation requirement."""
    rows = await self.call(self.client.spot.all_currencies)
    return [
      DepositMethod(
        asset=row['currency'],
        network=chain['chainId'],
        contract_address=chain['contractAddress'] or None,
        min_confirmations=chain['confirms'],
      )
      for row in rows
      if assets is None or row['currency'] in assets
      for chain in row['chains'] or []
      if chain['isDepositEnabled']
    ]

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    """Expose the per-chain minimum fee, not a quote for a specific withdrawal."""
    rows = await self.call(self.client.spot.all_currencies)
    return [
      WithdrawalMethod(
        asset=row['currency'],
        network=chain['chainId'],
        contract_address=chain['contractAddress'] or None,
        fee=WithdrawalMethod.Fee(
          asset=row['currency'], amount=Decimal(chain['withdrawalMinFee'])
        ),
      )
      for row in rows
      if assets is None or row['currency'] in assets
      for chain in row['chains'] or []
      if chain['isWithdrawEnabled']
      and (networks is None or chain['chainId'] in networks)
    ]
