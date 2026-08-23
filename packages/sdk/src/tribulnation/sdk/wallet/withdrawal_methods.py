from typing_extensions import Sequence, Collection
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import SDK

@dataclass(kw_only=True)
class WithdrawalMethod:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

    def __str__(self) -> str:
      return f'Fee({self.amount} {self.asset})'

  asset: str
  network: str
  fee: Fee | None = None
  contract_address: str | None = None

class WithdrawalMethods(SDK):
  @SDK.method
  @abstractmethod
  async def withdrawal_methods(
    self, *, assets: Collection[str] | None = None,
    networks: Collection[str] | None = None
  ) -> Sequence[WithdrawalMethod]:
    """Get withdrawal methods.

    - `assets`: optional filter by asset.
    - `networks`: optional filter by network.
    """