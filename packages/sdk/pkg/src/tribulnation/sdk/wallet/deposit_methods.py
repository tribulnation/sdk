from typing_extensions import Sequence, Collection
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
    self,
    *,
    assets: Collection[str] | None = None,
  ) -> Sequence[DepositMethod]:
    """Fetch the ways to deposit: one entry per asset and network.

    Args:
      assets: Keep methods for these assets only.
    """
