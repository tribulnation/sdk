"""Bybit's deposit methods, one per coin and chain."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.deposit_methods import (
  DepositMethod,
  DepositMethods as _DepositMethods,
)

from tribulnation.bybit.core import Mixin


@dataclass(kw_only=True, frozen=True)
class DepositMethods(Mixin, _DepositMethods):
  """Bybit's deposit catalogue."""

  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """Fetch the ways to deposit: one entry per coin and chain.

    `fee` is always `None`: Bybit charges no deposit fee, and `asset.coin_info`
    carries no deposit-fee field to report one from.

    Args:
      assets: Keep methods for these coins only.
    """
    coins = await self.call_bybit(
      lambda: self.client.asset.coin_info(validate=self.validate)
    )
    out: list[DepositMethod] = []
    for row in coins['rows']:
      if assets is not None and row['coin'] not in assets:
        continue
      for chain in row['chains']:
        if chain['chainDeposit'] != '1':
          continue
        # `confirmation` is declared `int`, but 15 of the 793 coins send `''` on a
        # chain with deposits disabled, which fails validation before this runs. The
        # guard is what will keep working once the client admits that sentinel.
        confirmations = chain['confirmation']
        out.append(
          DepositMethod(
            asset=row['coin'],
            network=chain['chain'],
            contract_address=chain['contractAddress'] or None,
            min_confirmations=int(confirmations) if confirmations else None,
          )
        )
    return out
