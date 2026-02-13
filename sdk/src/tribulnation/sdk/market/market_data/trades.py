from typing_extensions import Literal, AsyncIterable, Sequence
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import ChunkedStream, SDK

@dataclass
class Trade:
  id: str
  price: Decimal
  qty: Decimal
  """Base asset quantity."""
  time: datetime
  """Time of the transaction."""
  maker: Literal['buyer', 'seller']
  """Which side was the maker."""
  
class Trades(SDK):
  @SDK.method
  def trades(
    self, start: datetime, end: datetime
  ) -> ChunkedStream[Trade]:
    """Fetch market trades.
    
    - `start`: The start time to query. If given, only trades after this time will be returned.
    - `end`: The end time to query. If given, only trades before this time will be returned.
    """
    return ChunkedStream(self._trades_impl(start=start, end=end))
  
  @abstractmethod
  def _trades_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade]]:
    ...