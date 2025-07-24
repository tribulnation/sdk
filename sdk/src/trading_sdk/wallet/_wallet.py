from .deposit_address import DepositAddress
from .withdraw import Withdraw
from .withdrawal_methods import WithdrawalMethods

class Wallet(DepositAddress, Withdraw, WithdrawalMethods):
  ...