from dataclasses import dataclass
from typing_extensions import Protocol
from trading_sdk.types import Network

@dataclass
class Address:
  address: str
  memo: str | None = None

class DepositAddress(Protocol):
  async def deposit_address(self, asset: str, *, network: Network) -> Address:
    """Get the deposit address for an asset.
    
    - `asset`: The asset to get the deposit address for.
    - `network`: The network to get the deposit address for.
    """
    ...