from typing_extensions import Protocol, Sequence
from dataclasses import dataclass
from decimal import Decimal
from trading_sdk.types import Network

@dataclass
class WithdrawalMethod:

  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  network: Network
  fee: Fee | None = None
  contract_address: str | None = None

class WithdrawalMethods(Protocol):
  async def withdrawal_methods(self, asset: str) -> Sequence[WithdrawalMethod]:
    """Get the withdrawal methods for an asset.
    
    - `asset`: The asset to get the withdrawal methods for.
    """
    ...