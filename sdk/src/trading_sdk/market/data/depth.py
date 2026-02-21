from typing_extensions import Sequence, overload, Literal
from abc import abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from trading_sdk.core import SDK

@dataclass(kw_only=True)
class Book:
  
  @dataclass
  class Entry:
    price: Decimal
    qty: Decimal
    """Quantity in base units."""

    @property
    def notional(self) -> Decimal:
      return self.price * self.qty

    def __str__(self) -> str:
      return f'{self:f}'

    def __format__(self, fmt: str) -> str:
      return f'[{self.price:{fmt}}] {self.qty:{fmt}} (${self.notional:{fmt}})'

  bids: list[Entry] = field(default_factory=list)
  """Bids, sorted by price descending (best bid first)."""
  asks: list[Entry] = field(default_factory=list)
  """Asks, sorted by price ascending (best ask first)."""

  def __post_init__(self):
    self.bids.sort(key=lambda e: e.price, reverse=True)
    self.asks.sort(key=lambda e: e.price)

  @property
  def best_bid(self) -> Entry:
    return max(self.bids, key=lambda e: e.price)

  @property
  def best_ask(self) -> Entry:
    return min(self.asks, key=lambda e: e.price)

  @overload
  def market_buy_price(self, *, qty: Decimal) -> Decimal | None:
    """Average fill price for a market order buying `qty` base units."""
  @overload
  def market_buy_price(self, *, notional: Decimal) -> Decimal | None:
    """Average fill price for a market order buying `notional` value."""
  def market_buy_price(self, *, qty: Decimal | None = None, notional: Decimal | None = None) -> Decimal | None:
    if qty is not None:
      return market_price_qty(self.asks, qty)
    elif notional is not None:
      return market_price_notional(self.asks, notional)
    else:
      raise ValueError("Either qty or notional must be provided")

  @overload
  def market_sell_price(self, *, qty: Decimal) -> Decimal | None:
    """Average fill price for a market order selling `qty` base units."""
  @overload
  def market_sell_price(self, *, notional: Decimal) -> Decimal | None:
    """Average fill price for a market order selling `notional` value."""
  def market_sell_price(self, *, qty: Decimal | None = None, notional: Decimal | None = None) -> Decimal | None:
    if qty is not None:
      return market_price_qty(self.bids, qty)
    elif notional is not None:
      return market_price_notional(self.bids, notional)
    else:
      raise ValueError("Either qty or notional must be provided")

  def fillable_at(self, price: Decimal, *, side: Literal['buy', 'sell']) -> Decimal:
    """Max. fillable quantity at `price`."""
    if side == 'buy':
      return buyable_qty(self.bids, price)
    elif side == 'sell':
      return sellable_qty(self.asks, price)
    else:
      raise ValueError("Invalid side")

  def merge(self, *others: 'Book') -> 'Book':
    return Book(
      bids=self.bids + [e for other in others for e in other.bids],
      asks=self.asks + [e for other in others for e in other.asks],
    )

  def with_fees(self, fee: Decimal) -> 'Book':
    """Lower bids and raise asks to account for fees."""
    return Book(
      bids=[Book.Entry(e.price * (1 - fee), e.qty) for e in self.bids],
      asks=[Book.Entry(e.price * (1 + fee), e.qty) for e in self.asks],
    )

  def limit(self, levels: int) -> 'Book':
    """Limit the book to `levels` levels."""
    return Book(
      bids=self.bids[:levels],
      asks=self.asks[:levels],
    )

  @property
  def mark_price(self) -> Decimal:
    return (self.best_bid.price + self.best_ask.price) / 2

  def __str__(self) -> str:
    return f'{self:f}'

  def __format__(self, fmt: str) -> str:
    return fmt_book(self, fmt)


class Depth(SDK):
  Book = Book

  @SDK.method
  @abstractmethod
  async def book(self, *, limit: int | None = None) -> Book:
    """Fetch the market order book.
    
    - `limit`: The maximum number of bids/asks to return.
    """

  async def __call__(self, *, limit: int | None = None) -> Book:
    """Fetch the market order book.
    
    - `limit`: The maximum number of bids/asks to return.
    """
    return await self.book(limit=limit)



def avg_price(entries: Sequence['Book.Entry']) -> Decimal:
  total = sum(e.price * e.qty for e in entries)
  total_qty = sum(e.qty for e in entries)
  return Decimal(total) / Decimal(total_qty)


def market_price_qty(entries: list[Book.Entry], qty: Decimal) -> Decimal | None:
  """Average fill price for a market order consuming `qty` base units."""
  remaining = qty
  trades: list[Book.Entry] = []
  i = 0
  while remaining > 0 and i < len(entries):
    entry = entries[i]
    if entry.qty <= remaining:
      remaining -= entry.qty
      trades.append(entry)
      i += 1
    else:
      trades.append(Book.Entry(entry.price, remaining))
      remaining = Decimal(0)

  if remaining == 0:
    return avg_price(trades)


def market_price_notional(entries: list[Book.Entry], notional: Decimal) -> Decimal | None:
  """Average fill price for a market order consuming `notional` value."""
  remaining = notional
  trades: list[Book.Entry] = []
  i = 0
  while remaining > 0 and i < len(entries):
    entry = entries[i]
    if entry.notional <= remaining:
      remaining -= entry.notional
      trades.append(entry)
      i += 1
    else:
      trades.append(Book.Entry(entry.price, remaining / entry.price))
      remaining = Decimal(0)
  
  if remaining == 0:
    return avg_price(trades)


def buyable_qty(entries: list[Book.Entry], price: Decimal) -> Decimal:
  """Max. fillable quantity with average fill price <= `price`."""
  Q = Decimal(0) # total qty
  N = Decimal(0) # total notional
  P = price # target price
  for e in entries:
    if e.price <= P:
      Q += e.qty
      N += e.qty*e.price
    else:
      q = min((N - P*Q) / (P - e.price), e.qty)
      Q += q
      N += q*e.price
      if q < e.qty:
        break
  return Q


def sellable_qty(entries: list[Book.Entry], price: Decimal) -> Decimal:
  """Max. fillable quantity with average fill price >= `price`."""
  Q = Decimal(0) # total qty
  N = Decimal(0) # total notional
  P = price # target price
  for e in entries:
    if e.price >= P:
      Q += e.qty
      N += e.qty*e.price
    else:
      q = min((N - P*Q) / (P - e.price), e.qty)
      Q += q
      N += q*e.price
      if q < e.qty:
        break
  return Q

def with_fees(self: 'Book', fee: Decimal) -> 'Book':
  """Lower bids and raise asks to account for fees."""
  return Book(
    bids=[Book.Entry(e.price * (1-fee), e.qty) for e in self.bids],
    asks=[Book.Entry(e.price * (1+fee), e.qty) for e in self.asks],
  )

def fmt_book(self: 'Book', fmt: str) -> str:
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