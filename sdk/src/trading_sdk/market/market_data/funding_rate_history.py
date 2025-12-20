from typing_extensions import Protocol, AsyncIterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.util import ChunkedStream

@dataclass
class Funding:
  rate: Decimal
  time: datetime

class FundingRateHistory(Protocol):
  def funding_rate_history(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Funding]:
    """Fetch perpetual funding rate history."""
    return ChunkedStream(self._funding_rate_history_impl(start=start, end=end))
  
  def _funding_rate_history_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    ...
