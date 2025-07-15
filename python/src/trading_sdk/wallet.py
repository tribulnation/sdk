from typing_extensions import Protocol, TypedDict, NotRequired, Sequence
from decimal import Decimal

from trading_sdk.types import Num
from trading_sdk.errors import AuthedError

class Wallet(Protocol):
  async def withdraw(
    self, currency: str, *, address: str, amount: Num,
    network: str | None = None,
  ) -> AuthedError | None:
    ...

  async def get_deposit_address(self, currency: str, *, network: str | None = None) -> str | AuthedError:
    ...

  class WithdrawalMethod(TypedDict):
    network: str
    fee: Decimal
    min_amount: NotRequired[Decimal]

  async def get_withdrawal_methods(self, currency: str) -> Sequence[WithdrawalMethod] | AuthedError:
    ...