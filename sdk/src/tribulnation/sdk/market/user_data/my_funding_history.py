from typing_extensions import AsyncIterable, Sequence, Literal
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import SDK, ChunkedStream

@dataclass
class Funding:
  funding: Decimal
  time: datetime
  side: Literal['LONG', 'SHORT']
  currency: str
  rate: Decimal | None = None

class MyFundingHistory(SDK):
  @SDK.method
  def my_funding_history(
    self, start: datetime, end: datetime,
  ) -> ChunkedStream[Funding]:
    """Fetch your perpetual funding rate history."""
    return ChunkedStream(self._my_funding_history_impl(start=start, end=end))
  
  @abstractmethod
  def _my_funding_history_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Funding]]:
    ...