from typing_extensions import AsyncIterable
from abc import abstractmethod

from tribulnation.sdk.market.market_data.depth import Book
from tribulnation.sdk.core import SDK

class Depth(SDK):
  @SDK.method
  @abstractmethod
  def depth_stream(self, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of order book snapshots.
    
    - `limit`: The maximum number of bids/asks to return.
    """
    ...
    