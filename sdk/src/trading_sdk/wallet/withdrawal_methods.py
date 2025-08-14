from abc import ABC, abstractmethod
from typing_extensions import TypedDict, Sequence
from decimal import Decimal
from trading_sdk.types import Network

class WithdrawalMethod(TypedDict):
  network: Network
  contract_address: str
  fee: Decimal

class WithdrawalMethods(ABC):
  @abstractmethod
  async def withdrawal_methods(self, currency: str) -> Sequence[WithdrawalMethod]:
    """Get the withdrawal methods for a currency.
    
    - `currency`: The currency to get the withdrawal methods for.
    """
    ...