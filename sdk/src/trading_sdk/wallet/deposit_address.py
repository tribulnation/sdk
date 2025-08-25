from dataclasses import dataclass
from abc import ABC, abstractmethod
from trading_sdk.types import Network

@dataclass
class Address:
  address: str
  memo: str | None = None

class DepositAddress(ABC):
  @abstractmethod
  async def deposit_address(self, asset: str, *, network: Network) -> Address:
    """Get the deposit address for an asset.
    
    - `asset`: The asset to get the deposit address for.
    - `network`: The network to get the deposit address for.
    """
    ...