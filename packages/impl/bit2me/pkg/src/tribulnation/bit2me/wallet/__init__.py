"""Bit2Me's Wallet surface: deposit and withdrawal methods, per asset and network."""

from dataclasses import dataclass

from tribulnation.sdk.wallet import Wallet as _Wallet
from .deposit_methods import DepositMethods
from .networks import AssetNetwork, NetworkCache, Networks
from .withdrawal_methods import WithdrawalMethods


@dataclass(frozen=True, kw_only=True)
class Wallet(_Wallet, WithdrawalMethods, DepositMethods):
  """Bit2Me implementation of `Wallet`.

  Both methods share one `Networks` cache, so an enumeration that runs them in turn
  pays for the per-asset network lookups once.
  """
