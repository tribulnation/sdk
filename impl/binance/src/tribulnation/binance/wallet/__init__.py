from tribulnation.sdk import Wallet as _Wallet
from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods

class Wallet(_Wallet, DepositMethods, WithdrawalMethods):
  ...
