from abc import ABC, abstractmethod
from typing_extensions import TypedDict, NotRequired
from trading_sdk.types import Network

class Address(TypedDict):
  address: str
  memo: NotRequired[str | None]

class DepositAddress(ABC):
  @abstractmethod
  async def deposit_address(self, currency: str, *, network: Network) -> Address:
    """Get the deposit address for a currency.
    
    - `currency`: The currency to get the deposit address for.
    - `network`: The network to get the deposit address for.
    """
    ...