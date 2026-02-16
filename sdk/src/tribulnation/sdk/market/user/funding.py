from typing_extensions import Sequence, AsyncIterable
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import SDK

  
class Funding(SDK):
  @dataclass
  class Payment:
    amount: Decimal
    """Funding paid (if positive) or received (in quote units)"""
    time: datetime

  @SDK.method
  @abstractmethod
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Payment]]:
    """Fetch your funding payments."""

  async def history_sync(self, start: datetime, end: datetime) -> Sequence[Payment]:
    """Fetch your funding payments without streaming."""
    out: list[Funding.Payment] = []
    async for page in self.history(start, end):
      out.extend(page)
    return out