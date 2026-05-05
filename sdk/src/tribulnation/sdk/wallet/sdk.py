from tribulnation.sdk.core import SDK
from .deposit_methods import DepositMethods
from .withdrawal_methods import WithdrawalMethods

class Wallet(WithdrawalMethods, DepositMethods):
  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...