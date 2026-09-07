from dataclasses import dataclass as _dataclass

from tribulnation.sdk import Wallet as _Wallet
from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods


@_dataclass(kw_only=True, frozen=True)
class Wallet(_Wallet, WithdrawalMethods, DepositMethods):
  """Bybit's wallet surface."""
