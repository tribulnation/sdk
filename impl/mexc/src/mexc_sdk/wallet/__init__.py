from dataclasses import dataclass as _dataclass

from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods

@_dataclass(frozen=True)
class Wallet(DepositMethods, WithdrawalMethods):
  ...