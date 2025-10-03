from typing_extensions import Protocol, Sequence
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

  def market_buy_price(self, qty: Decimal) -> Decimal | None:
    remaining = qty
    trades: list[Book.Entry] = []
    i = 0
    while remaining > 0 and i < len(self.asks):
      ask = self.asks[i]
      if ask.qty <= remaining:
        remaining -= ask.qty
        trades.append(ask)
        i += 1
      else:
        trades.append(Book.Entry(ask.price, remaining))
        remaining = Decimal(0)

    if remaining == 0:
      return avg_price(trades)

  def market_sell_price(self, qty: Decimal) -> Decimal | None:
    remaining = qty
    trades: list[Book.Entry] = []
    i = 0
    while remaining > 0 and i < len(self.bids):
      bid = self.bids[i]
      if bid.qty <= remaining:
        remaining -= bid.qty
        trades.append(bid)
        i += 1
      else:
        trades.append(Book.Entry(bid.price, remaining))
        remaining = Decimal(0)
    
    if remaining == 0:
      return avg_price(trades)


  @property
  def mark_price(self) -> Decimal:
    return (self.best_bid.price + self.best_ask.price) / 2

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

def avg_price(entries: Sequence[Book.Entry]) -> Decimal:
  total = sum(e.price * e.qty for e in entries)
  total_qty = sum(e.qty for e in entries)
  return Decimal(total) / Decimal(total_qty)

class Depth(Protocol):
  async def depth(self, instrument: str, /, *, limit: int | None = None) -> Book:
    """Get the order book for a given symbol.
    
    - `instrument`: The instrument to get the depth for.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

class SpotDepth(Depth, Protocol):
  async def spot_depth(self, base: str, quote: str, /, *, limit: int | None = None) -> Book:
    """Get the order book for a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

class PerpDepth(Depth, Protocol):
  async def perp_depth(self, base: str, quote: str, /, *, limit: int | None = None) -> Book:
    """Get the order book for a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...

class InversePerpDepth(Depth, Protocol):
  async def inverse_perp_depth(self, currency: str, /, *, limit: int | None = None) -> Book:
    """Get the order book for a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...