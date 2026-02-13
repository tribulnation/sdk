from typing_extensions import Sequence
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import SDK

@dataclass(kw_only=True)
class DepositMethod:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  asset: str
  network: str
  fee: Fee | None = None
  contract_address: str | None = None
  min_confirmations: int | None = None

class DepositMethods(SDK):
  @SDK.method
  @abstractmethod
  async def deposit_methods(
    self, *, assets: Sequence[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """Get deposit methods.

    - `assets`: optional filter by asset.
    """