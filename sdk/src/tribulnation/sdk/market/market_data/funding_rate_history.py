from typing_extensions import AsyncIterable, Sequence
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import SDK, ChunkedStream

@dataclass
class Funding:
  rate: Decimal
  time: datetime

class FundingRateHistory(SDK):
  @SDK.method
  def funding_rate_history(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Funding]:
    """Fetch perpetual funding rate history."""
    return ChunkedStream(self._funding_rate_history_impl(start=start, end=end))
  
  @abstractmethod
  def _funding_rate_history_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    ...
