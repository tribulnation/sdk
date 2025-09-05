from typing_extensions import Protocol, AsyncIterable
from trading_sdk.spot.market_data.depth import Book

class Depth(Protocol):
  def depth(self, base: str, quote: str, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of Book snapshots for the given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...