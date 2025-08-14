from abc import ABC, abstractmethod
from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Num

@dataclass
class Reward:
  asset: Decimal
  qty: Decimal
  time: datetime

class RewardHistory(ABC):
  @abstractmethod
  async def reward_history(
    self, *, start: datetime | None = None,
    end: datetime | None = None
  ) -> AsyncIterable[Sequence[Reward]]:
    """Fetch earn rewards.
    
    - `start`: if given, retrieves rewards after this time.
    - `end`: if given, retrieves rewards before this time.
    """
    ...