from typing_extensions import Protocol, TypedDict, NotRequired, Sequence, Literal
from decimal import Decimal

from trading_sdk.types import Num

class Wallet(Protocol):
  async def withdraw(
    self, currency: str, *, address: str, amount: Num,
    network: str | None = None,
    unsafe: Literal[True]
  ) -> None: ...

  async def get_deposit_address(self, currency: str, *, network: str | None = None) -> str: ...

  class WithdrawalMethod(TypedDict):
    network: str
    fee: Decimal
    min_amount: NotRequired[Decimal]

  async def get_withdrawal_methods(self, currency: str) -> Sequence[WithdrawalMethod]: ...