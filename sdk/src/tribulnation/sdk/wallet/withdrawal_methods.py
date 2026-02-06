from typing_extensions import Protocol, Sequence
from dataclasses import dataclass
from decimal import Decimal
from tribulnation.sdk.core import SDK

@dataclass(kw_only=True)
class WithdrawalMethod:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  asset: str
  network: str
  fee: Fee | None = None
  contract_address: str | None = None

class WithdrawalMethods(SDK, Protocol):
  @SDK.method
  async def withdrawal_methods(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[str] | None = None
  ) -> Sequence[WithdrawalMethod]:
    """Get withdrawal methods.

    - `assets`: optional filter by asset.
    - `networks`: optional filter by network.
    """