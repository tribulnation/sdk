from typing_extensions import Protocol
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.market.types import Instrument

@dataclass
class Book:
  @dataclass
  class Entry:
    price: Decimal
    qty: Decimal

    def __str__(self) -> str:
      return f'{self:f}'

    def __format__(self, fmt: str) -> str:
      return f'[{self.price:{fmt}}] {self.qty:{fmt}}'

  bids: list[Entry]
  asks: list[Entry]

  @property
  def best_bid(self) -> Entry:
    return max(self.bids, key=lambda e: e.price)

  @property
  def best_ask(self) -> Entry:
    return min(self.asks, key=lambda e: e.price)

  def __str__(self) -> str:
    return f'{self:f}'

  def __format__(self, fmt: str) -> str:
    hr = '-'*16
    asks = sorted(self.asks, key=lambda e: e.price, reverse=True)
    bids = sorted(self.bids, key=lambda e: e.price, reverse=True)
    return (
      f'{hr}\nASKS\n{hr}\n' +
      '\n'.join(f'{e:{fmt}}' for e in asks) +
      f'\n{hr}\nBIDS\n{hr}\n' +
      '\n'.join(f'{e:{fmt}}' for e in bids) +
      f'\n{hr}'
    )

class Depth(Protocol):
  async def depth(self, instrument: Instrument, *, limit: int | None = None) -> Book:
    """Get the order book for a given symbol.
    
    - `instrument`: The instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

  async def depth_any(self, instrument: str, *, limit: int | None = None) -> Book:
    """Get the order book for a given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    return await self.depth({'type': 'any', 'name': instrument}, limit=limit)

  async def depth_spot(self, base: str, quote: str, *, limit: int | None = None) -> Book:
    """Get the order book for a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    return await self.depth({'type': 'spot', 'base': base, 'quote': quote}, limit=limit)

  async def depth_perp(self, base: str, quote: str, *, limit: int | None = None) -> Book:
    """Get the order book for a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    return await self.depth({'type': 'perp', 'base': base, 'quote': quote}, limit=limit)