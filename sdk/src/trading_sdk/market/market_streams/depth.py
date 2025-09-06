from typing_extensions import Protocol, AsyncIterable

from trading_sdk.market.market_data.depth import Book

class Depth(Protocol):
  def depth(self, instrument: str, /, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of book snapshots for the given instrument.
    
    - `instrument`: The instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...
    
class SpotDepth(Depth, Protocol):
  def spot_depth(self, base: str, quote: str, /, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of book snapshots for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

class PerpDepth(Depth, Protocol):
  def perp_depth(self, base: str, quote: str, /, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of book snapshots for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

class InversePerpDepth(Depth, Protocol):
  def inverse_perp_depth(self, currency: str, /, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of book snapshots for the given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...