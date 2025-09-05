from typing_extensions import Protocol, AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Network

@dataclass
class Withdrawal:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  id: str
  amount: Decimal
  asset: str
  time: datetime
  address: str | None = None
  network: Network | None = None
  fee: Fee | None = None
  memo: str | None = None

class WithdrawalHistory(Protocol):
  def withdrawal_history(
    self, *, asset: str | None = None,
    start: datetime,
    end: datetime,
  ) -> AsyncIterable[Sequence[Withdrawal]]:
    """Fetch your withdrawals.
    
    - `asset`: if given, retrieves withdrawals for this asset.
    - `start`: if given, retrieves withdrawals after this time.
    - `end`: if given, retrieves withdrawals before this time.
    """
    ...