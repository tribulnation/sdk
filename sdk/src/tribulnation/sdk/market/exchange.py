from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime

from tribulnation.sdk.core import SDK, PaginatedResponse
from .types import (
  Book,
  NextFunding,
  Order, OrderResponse, OrderState,
  Position, PerpPosition,
  Trade,
  Rules,
)
from .settings import Settings
from .market import Market, PerpMarket

class Exchange(SDK):
  """An abstract multi-market exchange interface."""

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...

  @property
  def venue_id(self) -> str:
    ...

  @property
  def exchange_id(self) -> str:
    ...

  @property
  def id(self) -> str:
    return f'{self.venue_id}:{self.exchange_id}'

  @abstractmethod
  async def market(self, market_id: str, /) -> Market:
    """Fetch a market by ID."""

  @abstractmethod
  async def markets(self) -> Sequence[str]:
    """List available markets."""
  
  @SDK.method
  async def depth(self, market_id: str, /, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""
    market = await self.market(market_id)
    return await market.depth(levels=levels)

  @SDK.method
  def depth_stream(self, market_id: str, /, *, levels: int | None = None) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book."""
    return self._depth_stream_impl(market_id, levels=levels)

  @asynccontextmanager
  async def _depth_stream_impl(self, market_id: str, /, *, levels: int | None = None):
    market = await self.market(market_id)
    async with market.depth_stream(levels=levels) as stream:
      yield stream
  
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
  @PaginatedResponse.lift
  async def trades_history(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch your trades history."""
    market = await self.market(market_id)
    async for page in market.trades_history(start, end):
      yield page

  @SDK.method
  def trades_stream(self, market_id: str, /) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades."""
    return self._trades_stream_impl(market_id)

  @asynccontextmanager
  async def _trades_stream_impl(self, market_id: str, /):
    market = await self.market(market_id)
    async with market.trades_stream() as stream:
      yield stream

  @SDK.method
  async def position(self, market_id: str, /) -> Position:
    """Fetch your open position in the market."""
    market = await self.market(market_id)
    return await market.position()

  @SDK.method
  async def available_notional(self, market_id: str, /):
    """Fetch the max. notional position you can open.
    
    - For spot, returns the free quote token balance
    - For futures, returns the available collateral times the maximum leverage
    """
    market = await self.market(market_id)
    return await market.available_notional()

  @SDK.method
  async def place_order(self, market_id: str, /, order: Order, *, settings: Settings = {}) -> OrderResponse:
    """Place an order in the market."""
    market = await self.market(market_id)
    return await market.place_order(order, settings=settings)

  @SDK.method
  async def cancel_order(self, market_id: str, /, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order in the market."""
    market = await self.market(market_id)
    return await market.cancel_order(id, settings=settings)

  @SDK.method
  async def cancel_orders(self, market_id: str, /, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel multiple orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_orders(ids, settings=settings)

  @SDK.method
  async def cancel_open_orders(self, market_id: str, /, *, settings: Settings = {}) -> Any:
    """Cancel all open orders in the market."""
    market = await self.market(market_id)
    return await market.cancel_open_orders(settings=settings)


class PerpExchange(Exchange):
  """An abstract perpetual exchange interface."""
  @SDK.method
  @abstractmethod
  async def market(self, market_id: str, /) -> PerpMarket:
    """Fetch a perpetual market by ID."""

  @SDK.method
  async def index(self, market_id: str, /, *, settings: Settings = {}):
    """Fetch the market index price."""
    market = await self.market(market_id)
    return await market.index(settings=settings)

  @SDK.method
  async def next_funding(self, market_id: str, /) -> NextFunding:
    """Fetch the next funding rate and time."""
    market = await self.market(market_id)
    return await market.next_funding()

  @SDK.method
  @PaginatedResponse.lift
  async def funding_history(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch perpetual funding rate history."""
    market = await self.market(market_id)
    async for page in market.funding_history(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch your funding payments history."""
    market = await self.market(market_id)
    async for page in market.funding_payments(start, end):
      yield page

  @SDK.method
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
    market = await self.market(market_id)
    return await market.perp_position()
