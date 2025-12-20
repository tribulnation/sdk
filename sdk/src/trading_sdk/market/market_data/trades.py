from typing_extensions import Protocol, Literal, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.util import ChunkedStream

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
  
class Trades(Protocol):
  async def trades(
    self, start: datetime, end: datetime
  ) -> ChunkedStream[Trade]:
    """Fetch market trades."""
    return ChunkedStream(self._trades_impl(start=start, end=end))
  
  def _trades_impl(
    self, start: datetime, end: datetime,
  ) -> AsyncIterable[Sequence[Trade]]:
    ...