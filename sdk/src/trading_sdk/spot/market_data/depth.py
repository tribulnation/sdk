from typing_extensions import Protocol
from dataclasses import dataclass
from decimal import Decimal

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
  async def depth(self, base: str, quote: str, *, limit: int | None = None) -> Book:
    """Get the order book for a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...