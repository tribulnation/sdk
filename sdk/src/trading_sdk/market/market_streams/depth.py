from typing_extensions import Protocol, AsyncIterable

from trading_sdk.market.market_data.depth import Book

class Depth(Protocol):
  def depth_stream(self, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of order book snapshots.
    
    - `limit`: The maximum number of bids/asks to return.
    """
    ...
    