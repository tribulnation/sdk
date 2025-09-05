from typing_extensions import Protocol, AsyncIterable

from trading_sdk.market.market_data.depth import Book
from trading_sdk.market.types import Instrument

class Depth(Protocol):
  def depth(self, instrument: Instrument, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of Book snapshots for the given instrument.
    
    - `instrument`: The instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

  async def depth_any(self, instrument: str, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of Book snapshots for the given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    async for book in self.depth({'type': 'any', 'name': instrument}, limit=limit):
      yield book
    

  async def depth_spot(self, base: str, quote: str, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of Book snapshots for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    async for book in self.depth({'type': 'spot', 'base': base, 'quote': quote}, limit=limit):
      yield book
    
  async def depth_perp(self, base: str, quote: str, *, limit: int | None = None) -> AsyncIterable[Book]:
    """Stream of Book snapshots for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    async for book in self.depth({'type': 'perp', 'base': base, 'quote': quote}, limit=limit):
      yield book
    