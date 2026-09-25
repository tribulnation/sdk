"""Explicit Wallet gaps pending Aster's missing typed asset catalogues."""

from dataclasses import dataclass
from typing_extensions import Collection, Sequence
from tribulnation.sdk.wallet import Wallet as SDKWallet
from tribulnation.sdk.wallet.deposit_methods import DepositMethod
from tribulnation.sdk.wallet.withdrawal_methods import WithdrawalMethod
from .core import SharedMixin


@dataclass(frozen=True, kw_only=True)
class Wallet(SharedMixin, SDKWallet):
  """Expose accurate unsupported-method errors through the Wallet router."""

  async def deposit_methods(
    self, *, assets: Collection[str] | None = None
  ) -> Sequence[DepositMethod]:
    """The typed client lacks the documented deposit asset/network catalogue."""
    raise NotImplementedError(
      'Aster lacks the documented deposit and withdrawal asset catalogues'
    )

  async def withdrawal_methods(
    self,
    *,
    assets: Collection[str] | None = None,
    networks: Collection[str] | None = None,
  ) -> Sequence[WithdrawalMethod]:
    """The typed client lacks the documented withdrawal asset/network catalogue."""
    raise NotImplementedError(
      'Aster lacks the documented deposit and withdrawal asset catalogues'
    )
