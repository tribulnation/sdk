from typing_extensions import Protocol, AsyncIterable, Sequence, Literal
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from sdk.core import ChunkedStream

@dataclass
class Funding:
  funding: Decimal
  time: datetime
  side: Literal['LONG', 'SHORT']
  currency: str
  rate: Decimal | None = None

class MyFundingHistory(Protocol):
  def my_funding_history(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Funding]:
    """Fetch your perpetual funding rate history."""
    return ChunkedStream(self._my_funding_history_impl(start=start, end=end))
  
  def _my_funding_history_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    ...