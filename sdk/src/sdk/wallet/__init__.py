from typing_extensions import Protocol

from .deposit_methods import DepositMethods
from .withdraw import Withdraw
from .withdrawal_methods import WithdrawalMethods

class Wallet(Withdraw, WithdrawalMethods, DepositMethods, Protocol):
  ...