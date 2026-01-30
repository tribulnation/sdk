from typing_extensions import Protocol, Sequence, AsyncGenerator, Any
from dataclasses import dataclass
from decimal import Decimal
from sdk.core import SDK, Network, ChunkedStream

@dataclass(kw_only=True)
class WithdrawalMethod:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  asset: str
  contract_address: str | None = None
  network: Network
  fee: Fee | None

class WithdrawalMethods(SDK, Protocol):
  @SDK.method
  def withdrawal_methods(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[Network] | None = None
  ) -> ChunkedStream[WithdrawalMethod]:
    """Get withdrawal methods.

    - `assets`: optional filter by asset.
    - `networks`: optional filter by network.
    """
    return ChunkedStream(self._withdrawal_methods_impl(assets=assets, networks=networks))
  
  def _withdrawal_methods_impl(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[Network] | None = None
  ) -> AsyncGenerator[Sequence[WithdrawalMethod], Any]:
    ...