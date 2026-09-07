"""Bit2Me implementation of the `deposit_methods` wallet endpoint."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.deposit_methods import (
  DepositMethod,
  DepositMethods as _DepositMethods,
)

from .networks import Networks


@dataclass(frozen=True, kw_only=True)
class DepositMethods(_DepositMethods, Networks):
  """Bit2Me implementation of `DepositMethods`.

  `fee`, `contract_address` and `min_confirmations` are always `None`: neither the
  asset catalogue nor the per-asset network list carries a deposit fee, a contract
  address (despite the catalogue's `isERC20Token` flag), or a confirmations count,
  and there is no per-network deposit-enabled flag distinct from the whole-asset
  `enabled` one. The networks' `hasTag` -- whether an address on that chain needs a
  memo -- has no field on `DepositMethod` to land in.
  """

  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    pairs = await self.asset_networks(assets=assets)
    return [
      DepositMethod(asset=pair.asset, network=pair.network['id']) for pair in pairs
    ]
