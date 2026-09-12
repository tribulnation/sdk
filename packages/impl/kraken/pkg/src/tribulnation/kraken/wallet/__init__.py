"""Kraken's Wallet surface: withdrawal methods per asset and network."""

from dataclasses import dataclass

from tribulnation.sdk.wallet import Wallet as _Wallet
from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods


@dataclass(frozen=True, kw_only=True)
class Wallet(_Wallet, WithdrawalMethods, DepositMethods):
  """Kraken implementation of `Wallet`."""
