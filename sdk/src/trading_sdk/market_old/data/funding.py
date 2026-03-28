from typing_extensions import AsyncIterable, Sequence
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.core import SDK

@dataclass
class FundingRate:
  rate: Decimal
  """Funding rate (in relative units, e.g. 0.01 = 1%)."""
  time: datetime
  """Funding payment time."""

class Funding(SDK):
  Funding = FundingRate
  
  @SDK.method
  @abstractmethod
  def history(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    """Fetch perpetual funding rate history."""

  async def history_sync(self, start: datetime, end: datetime) -> Sequence[Funding]:
    """Fetch perpetual funding rate history without streaming."""
    out: list[Funding.Funding] = []
    async for page in self.history(start, end):
      out.extend(page)
    return out

  @SDK.method
  @abstractmethod
  async def next(self) -> Funding:
    """Fetch the next funding rate and time."""
