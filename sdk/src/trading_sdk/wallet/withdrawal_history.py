from typing_extensions import AsyncIterable, Sequence
from abc import ABC, abstractmethod
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
  address: str
  amount: Decimal
  asset: str
  network: Network
  time: datetime
  fee: Fee | None = None
  memo: str | None = None

class WithdrawalHistory(ABC):
  @abstractmethod
  def withdrawal_history(
    self, *, start: datetime | None = None,
    end: datetime | None = None
  ) -> AsyncIterable[Sequence[Withdrawal]]:
    """Fetch your withdrawals.
    
    - `start`: if given, retrieves withdrawals after this time.
    - `end`: if given, retrieves withdrawals before this time.
    """
    ...