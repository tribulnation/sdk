"""Kraken's `deposit_methods` wallet endpoint, deliberately unimplemented."""

from typing_extensions import Collection, Sequence
from dataclasses import dataclass

from tribulnation.sdk.wallet.deposit_methods import (
  DepositMethod,
  DepositMethods as _DepositMethods,
)
from tribulnation.kraken.core import Mixin


@dataclass(frozen=True, kw_only=True)
class DepositMethods(_DepositMethods, Mixin):
  """Kraken's `DepositMethods` cannot fill a `DepositMethod`.

  The endpoint answers one asset at a time with rows carrying a `method` name
  (`Bitcoin`, `Bitcoin Lightning`, `kBTC - Optimism (Unified)`) that conflates the
  network with the delivery mechanism, and no `network` field at all; the
  withdrawal side names networks properly, the deposit side does not. Emitting the
  method name as a network would be a stand-in, so this raises instead.
  """

  async def deposit_methods(
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    raise NotImplementedError(
      'deposit_methods is not implemented for Kraken: `DepositMethods` returns a '
      'per-asset method name and no network field, so there is no network to report.'
    )
