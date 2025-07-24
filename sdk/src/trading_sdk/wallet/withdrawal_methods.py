from typing_extensions import Protocol, TypedDict, Sequence
from decimal import Decimal

class WithdrawalMethod(TypedDict):
  network: str
  contract_address: str
  fee: Decimal

class WithdrawalMethods(Protocol):
  async def withdrawal_methods(self, currency: str) -> Sequence[WithdrawalMethod]:
    """Get the withdrawal methods for a currency.
    
    - `currency`: The currency to get the withdrawal methods for.
    """
    ...