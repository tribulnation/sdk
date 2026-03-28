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
from .market import Market, PerpMarket

class Exchange(SDK):
  """An abstract multi-market exchange interface."""
  
  @abstractmethod
  async def market(self, market_id: str, /) -> Market:
    """Fetch a market by ID."""

  @abstractmethod
  async def markets(self) -> Sequence[str]:
    """List available markets."""
  
  @SDK.method
  async def depth(self, market_id: str, /) -> Book:
    """Fetch the market order book."""
    market = await self.market(market_id)
    return await market.depth()

  @SDK.method
  async def depth_stream(self, market_id: str, /) -> AsyncIterable[Book]:
    """Subscribe to the market order book."""
    market = await self.market(market_id)
    stream = await market.depth_stream()
    async for book in stream:
      yield book
  
  @SDK.method
  async def rules(self, market_id: str, /, *, refetch: bool = False) -> Rules:
    """Fetch the market rules.
    
    - `refetch`: if `True`, fetch the rules even if they are already cached.
    """
    market = await self.market(market_id)
    return await market.rules(refetch=refetch)

  @SDK.method
  async def query_order(self, market_id: str, /, id: str) -> OrderState | None:
    """Fetch the state of the order with the given ID."""
    market = await self.market(market_id)
    return await market.query_order(id)

  @SDK.method
  async def open_orders(self, market_id: str, /) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    market = await self.market(market_id)
    return await market.open_orders()

  @SDK.method
  async def trades_history(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
    """Fetch your trades history."""
    market = await self.market(market_id)
    async for page in market.trades_history(start, end):
      yield page

  @SDK.method
  async def trades_stream(self, market_id: str, /) -> AsyncIterable[Trade]:
    """Subscribe to your real-time trades."""
    market = await self.market(market_id)
    async for trade in await market.trades_stream():
      yield trade

  @SDK.method
  async def position(self, market_id: str, /) -> Position:
    """Fetch your open position in the market."""
    market = await self.market(market_id)
    return await market.position()

  @SDK.method
  async def place_order(self, market_id: str, /, order: Order) -> OrderResponse:
    """Place an order in the market."""
    market = await self.market(market_id)
    return await market.place_order(order)

  @SDK.method
  async def cancel_order(self, market_id: str, /, id: str) -> Any:
    """Cancel an order in the market."""
    market = await self.market(market_id)
    return await market.cancel_order(id)

  @SDK.method
  async def cancel_orders(self, market_id: str, /, ids: Sequence[str]) -> Any:
    """Cancel multiple orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_orders(ids)

  @SDK.method
  async def cancel_open_orders(self, market_id: str, /) -> Any:
    """Cancel all open orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_open_orders()


class PerpExchange(Exchange):
  """An abstract perpetual exchange interface."""
  @SDK.method
  @abstractmethod
  async def market(self, market_id: str, /) -> PerpMarket:
    """Fetch a perpetual market by ID."""

  @SDK.method
  async def funding_history(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]:
    """Fetch perpetual funding rate history."""
    market = await self.market(market_id)
    async for page in market.funding_history(start, end):
      yield page

  @SDK.method
  async def funding_paymets(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch your funding payments history."""
    market = await self.market(market_id)
    async for page in market.funding_paymets(start, end):
      yield page

  @SDK.method
  async def position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the market."""
    market = await self.market(market_id)
    return await market.position()