from typing_extensions import Protocol
from .deposit_address import DepositAddress
from .withdraw import Withdraw
from .withdrawal_methods import WithdrawalMethods
from .deposit_history import DepositHistory
from .withdrawal_history import WithdrawalHistory

class Wallet(DepositAddress, Withdraw, WithdrawalMethods, DepositHistory, WithdrawalHistory, Protocol):
  ...