"""Public Deribit network methods, with currency-level withdrawal fees."""

from decimal import Decimal
from typing_extensions import Collection, Sequence
from typed_deribit.market_data.get_currencies import CurrencyItem
from tribulnation.sdk.wallet import Wallet as BaseWallet
from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod
from .core import Mixin


def networks_of(row: CurrencyItem) -> list[str]:
  """Keep venue network identifiers; do not infer token contracts."""
  networks = row.get('coinbase_networks')
  if not networks:
    return [row['coin_type']]
  return list(
    dict.fromkeys(
      network.get('display_name') or network.get('resource_name') or row['coin_type']
      for network in networks
    )
  )


class Wallet(Mixin, BaseWallet):
  """Read supported networks without creating addresses or moving funds."""

  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """List published deposit networks; no deposit fee or contract is supplied."""
    rows = await self.call(self.client.market_data.get_currencies)
    return [
      DepositMethod(
        asset=row['currency'],
        network=network,
        min_confirmations=row['min_confirmations'],
      )
      for row in rows
      if assets is None or row['currency'] in assets
      for network in networks_of(row)
    ]

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    """List published networks with the currency-level fee, not a withdrawal quote."""
    rows = await self.call(self.client.market_data.get_currencies)
    return [
      WithdrawalMethod(
        asset=row['currency'],
        network=network,
        fee=WithdrawalMethod.Fee(
          asset=row['currency'], amount=Decimal(str(row['withdrawal_fee']))
        ),
      )
      for row in rows
      if assets is None or row['currency'] in assets
      for network in networks_of(row)
      if networks is None or network in networks
    ]
