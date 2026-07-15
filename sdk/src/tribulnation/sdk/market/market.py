from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import SDK, PaginatedResponse
from .types import (
  Book,
  FundingRate, NextFunding, FundingPayment,
  Order, OrderResponse, OrderState,
  Position, PerpPosition,
  Trade,
  Rules,
)
from .settings import Settings

class Market(SDK):
  """An abstract market interface."""

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...

  @property
  def market_id(self) -> str:
    ...

  @property
  def exchange_id(self) -> str:
    ...

  @property
  def venue_id(self) -> str:
    ...

  @property
  def id(self) -> str:
    return f'{self.venue_id}:{self.exchange_id}:{self.market_id}'

  @SDK.method
  @abstractmethod
  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""
  
  @SDK.method
  def depth_stream(self, *, levels: int | None = None) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return self._depth_stream_default(levels=levels)

  @asynccontextmanager
  async def _depth_stream_default(self, *, levels: int | None = None):
    async def gen():
      while True:
        yield await self.depth(levels=levels)
    yield gen()

  @SDK.method
  @abstractmethod
  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch the market rules.
    
    - `refetch`: if `True`, fetch the rules even if they are already cached.
    """

  @SDK.method
  async def query_order(self, id: str) -> OrderState | None:
    """Fetch the state of the order with the given ID."""
    open_orders = await self.open_orders()
    for order in open_orders:
      if order.id == id:
        return order

  @SDK.method
  @abstractmethod
  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""

  @SDK.method
  @abstractmethod
  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fetch your trades history."""

  @SDK.method
  @abstractmethod
  def trades_stream(self) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""

  @SDK.method
  @abstractmethod
  async def position(self) -> Position:
    """Fetch your open position in the market."""

  @SDK.method
  @abstractmethod
  async def available_notional(self) -> Decimal:
    """Fetch the max. notional position you can open.
    
    - For spot, returns the free quote token balance
    - For futures, returns the available collateral times the maximum leverage
    """

  @SDK.method
  @abstractmethod
  async def place_order(self, order: Order, *, settings: Settings = {}) -> OrderResponse:
    """Place an order in the market."""

  @SDK.method
  async def place_orders(self, orders: Sequence[Order], *, settings: Settings = {}) -> Sequence[OrderResponse]:
    """Place multiple orders in the market."""
    return await asyncio.gather(*[self.place_order(order, settings=settings) for order in orders])

  @SDK.method
  @abstractmethod
  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order in the market."""

  @SDK.method
  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel multiple orders in the market."""
    return await asyncio.gather(*[self.cancel_order(id, settings=settings) for id in ids])

  @SDK.method
  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel all open orders in the market."""
    open_orders = await self.open_orders()
    return await self.cancel_orders([order.id for order in open_orders], settings=settings)


class PerpMarket(Market):
  """An abstract perpetual market interface."""
  @SDK.method
  @abstractmethod
  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Fetch the market index price."""

  @SDK.method
  @abstractmethod
  async def next_funding(self) -> NextFunding:
    """Fetch the next funding rate and time."""

  @SDK.method
  @abstractmethod
  def funding_history(self, start: datetime, end: datetime) -> PaginatedResponse[FundingRate]:
    """Fetch perpetual funding rate history."""

  @SDK.method
  @abstractmethod
  def funding_payments(self, start: datetime, end: datetime) -> PaginatedResponse[FundingPayment]:
    """Fetch your funding payments history."""

  @SDK.method
  async def position(self) -> Position:
    """Fetch your open position in the market."""
    return await self.perp_position()

  @SDK.method
  @abstractmethod
  async def perp_position(self) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
