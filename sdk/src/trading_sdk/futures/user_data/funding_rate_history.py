from abc import ABC, abstractmethod
from typing_extensions import AsyncIterable, Sequence, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

PositionType = Literal['LONG', 'SHORT']

@dataclass
class Funding:
  rate: Decimal
  funding: Decimal
  """Funding paid (if negative) or earned (if positive)."""
  time: datetime
  position_type: PositionType

class FundingRateHistory(ABC):
  @abstractmethod
  def funding_rate_history(
    self, base: str, quote: str, *, start: datetime | None = None,
    end: datetime | None = None,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch funding rate history for a given symbol.

    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `start`: if given, retrieves funding rates after this time.
    - `end`: if given, retrieves funding rates before this time.
    """
    ...