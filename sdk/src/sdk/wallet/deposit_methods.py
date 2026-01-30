from typing_extensions import Protocol, Sequence, AsyncGenerator, Any
from dataclasses import dataclass
from decimal import Decimal
from sdk.core import SDK, Network, ChunkedStream

@dataclass(kw_only=True)
class DepositMethod:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  asset: str
  address: str
  memo: str | None = None
  network: Network
  fee: Fee | None
  min_confirmations: int | None = None

class DepositMethods(SDK, Protocol):
  @SDK.method
  def deposit_methods(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[Network] | None = None
  ) -> ChunkedStream[DepositMethod]:
    return ChunkedStream(self._deposit_methods_impl(assets=assets, networks=networks))

  def _deposit_methods_impl(
    self, *, assets: Sequence[str] | None = None,
    networks: Sequence[Network] | None = None
  ) -> AsyncGenerator[Sequence[DepositMethod], Any]:
    ...