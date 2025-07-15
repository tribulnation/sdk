from typing_extensions import Protocol, TypedDict, NotRequired, Sequence, overload, Literal
from decimal import Decimal

from trading_sdk.types import Num
from trading_sdk.errors import AuthedError

class Wallet(Protocol):
  @overload
  async def withdraw(
    self, currency: str, *, address: str, amount: Num,
    network: str | None = None,
    unsafe: Literal[True]
  ) -> None: ...
  @overload
  async def withdraw(
    self, currency: str, *, address: str, amount: Num,
    network: str | None = None,
    unsafe: bool = False
  ) -> AuthedError | None: ...

  @overload
  async def get_deposit_address(self, currency: str, *, network: str | None = None, unsafe: Literal[True]) -> str: ...
  @overload
  async def get_deposit_address(self, currency: str, *, network: str | None = None, unsafe: bool = False) -> str | AuthedError: ...

  class WithdrawalMethod(TypedDict):
    network: str
    fee: Decimal
    min_amount: NotRequired[Decimal]

  @overload
  async def get_withdrawal_methods(self, currency: str, *, unsafe: Literal[True]) -> Sequence[WithdrawalMethod]: ...
  @overload
  async def get_withdrawal_methods(self, currency: str, *, unsafe: bool = False) -> Sequence[WithdrawalMethod] | AuthedError: ...