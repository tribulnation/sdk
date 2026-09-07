"""Bybit's withdrawal methods, one per coin and chain."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.withdrawal_methods import (
  WithdrawalMethod,
  WithdrawalMethods as _WithdrawalMethods,
)

from tribulnation.bybit.core import Mixin


@dataclass(kw_only=True, frozen=True)
class WithdrawalMethods(Mixin, _WithdrawalMethods):
  """Bybit's withdrawal catalogue."""

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    """Fetch the ways to withdraw: one entry per coin and chain, with its fee.

    Only the fixed `withdrawFee` is carried over. Bybit also applies a
    `withdrawPercentageFee` on a handful of coin/chain pairs, and the SDK's `Fee`
    shape (an asset and an amount) has nowhere to put a percentage component.

    Args:
      assets: Keep methods for these coins only.
      networks: Keep methods on these chains only.
    """
    coins = await self.call_bybit(
      lambda: self.client.asset.coin_info(validate=self.validate)
    )
    out: list[WithdrawalMethod] = []
    for row in coins['rows']:
      if assets is not None and row['coin'] not in assets:
        continue
      for chain in row['chains']:
        if chain['chainWithdraw'] != '1':
          continue
        if networks is not None and chain['chain'] not in networks:
          continue
        # `withdrawFee` is `''` on the chains that support no withdrawal at all,
        # none of which get past the filter above. Test for that sentinel rather
        # than for truthiness: a free withdrawal is not an unknown fee, and plenty
        # of withdraw-enabled chains charge exactly `0`.
        raw_fee = chain['withdrawFee']
        out.append(
          WithdrawalMethod(
            asset=row['coin'],
            network=chain['chain'],
            fee=None
            if raw_fee == ''
            else WithdrawalMethod.Fee(asset=row['coin'], amount=raw_fee),
            contract_address=chain['contractAddress'] or None,
          )
        )
    return out
