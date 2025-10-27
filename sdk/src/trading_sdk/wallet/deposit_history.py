from typing_extensions import Protocol, AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Network

@dataclass
class Deposit:
  @dataclass
  class Fee:
    asset: str
    amount: Decimal

  id: str
  amount: Decimal
  asset: str
  time: datetime
  source_address: str
  network: Network
  fee: Fee | None = None
  source_memo: str | None = None

class DepositHistory(Protocol):
  def deposit_history(
    self, asset: str, /, *,
    start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Deposit]]:
    """Fetch your deposits.
    
    - `asset`: The asset to get the deposit history for.
    - `start`: retrieves deposits after this time.
    - `end`: retrieves deposits before this time.
    """
    ...