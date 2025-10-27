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
  dest_address: str
  network: Network
  fee: Fee | None = None
  dest_memo: str | None = None

class WithdrawalHistory(Protocol):
  def withdrawal_history(
    self, asset: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Withdrawal]]:
    """Fetch your withdrawals.
    
    - `asset`: The asset to get the withdrawal history for.
    - `start`: retrieves withdrawals after this time.
    - `end`: retrieves withdrawals before this time.
    """
    ...