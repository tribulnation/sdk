from typing_extensions import Any, AsyncIterable, Sequence
from abc import abstractmethod
from datetime import datetime
from decimal import Decimal
import asyncio

from trading_sdk import SDK
from .types import (
  Book,
  FundingRate, FundingPayment,
  Order, OrderResponse, OrderState,
  Position, PerpPosition,
  Trade,
  Rules,
)

class Market(SDK):
  """An abstract market interface."""
  @SDK.method
  @abstractmethod
  async def depth(self) -> Book:
    """Fetch the market order book."""
  
  @SDK.method
  async def depth_stream(self) -> AsyncIterable[Book]:
    """Subscribe to the market order book."""
    async def stream():
      while True:
        yield await self.depth()
    return stream()

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
  def trades_history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
    """Fetch your trades history."""

  @SDK.method
  @abstractmethod
  async def trades_stream(self) -> AsyncIterable[Trade]:
    """Subscribe to your real-time trades."""
    # YES: the intended usage is `async for trade in await self.trades_stream(): ...`
    # After the `await`, the stream is operational - thus no trades will be missed during start-up.

  @SDK.method
  @abstractmethod
  async def position(self) -> Position:
    """Fetch your open position in the market."""

  @SDK.method
  @abstractmethod
  async def place_order(self, order: Order) -> OrderResponse:
    """Place an order in the market."""

  @SDK.method
  async def place_orders(self, orders: Sequence[Order]) -> Sequence[OrderResponse]:
    """Place multiple orders in the market."""
    return await asyncio.gather(*[self.place_order(order) for order in orders])

  @SDK.method
  @abstractmethod
  async def cancel_order(self, id: str) -> Any:
    """Cancel an order in the market."""

  @SDK.method
  async def cancel_orders(self, ids: Sequence[str]) -> Any:
    """Cancel multiple orders in the market."""
    return await asyncio.gather(*[self.cancel_order(id) for id in ids])

  @SDK.method
  async def cancel_open_orders(self) -> Any:
    """Cancel all open orders in the market."""
    open_orders = await self.open_orders()
    return await self.cancel_orders([order.id for order in open_orders])


class PerpMarket(Market):
  """An abstract perpetual market interface."""
  @SDK.method
  @abstractmethod
  async def index(self) -> Decimal:
    """Fetch the market index price."""

  @SDK.method
  @abstractmethod
  async def next_funding(self) -> FundingRate:
    """Fetch the next funding rate and time."""

  @SDK.method
  @abstractmethod
  def funding_history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]:
    """Fetch perpetual funding rate history."""

  @SDK.method
  @abstractmethod
  def funding_paymets(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch your funding payments history."""

  @SDK.method
  @abstractmethod
  async def position(self) -> PerpPosition:
    """Fetch your open position in the market."""