from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from abc import ABC, abstractmethod
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
  network: Network
  address: str
  time: datetime
  fee: Fee | None = None
  memo: str | None = None

class DepositHistory(ABC):
  @abstractmethod
  def deposit_history(
    self, *, start: datetime | None = None,
    end: datetime | None = None
  ) -> AsyncIterable[Sequence[Deposit]]:
    """Fetch your deposits.
    
    - `start`: if given, retrieves deposits after this time.
    - `end`: if given, retrieves deposits before this time.
    """
    ...