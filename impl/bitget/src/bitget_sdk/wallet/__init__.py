from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods

class Wallet(DepositMethods, WithdrawalMethods):
  ...