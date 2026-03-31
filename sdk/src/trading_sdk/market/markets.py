from typing_extensions import Any, AsyncIterable, Sequence, Literal, TypedDict
from abc import abstractmethod
from datetime import datetime

from trading_sdk.core import SDK, PaginatedResponse
from .types import (
  Book,
  FundingRate, FundingPayment,
  Order, OrderResponse, OrderState,
  Position, PerpPosition,
  Trade,
  Rules,
)
from .market import Market
from .exchange import Exchange, PerpExchange
from .venue import TradingVenue

class TradingMarkets(SDK):
  """A collection of all venues supported by the SDK."""

  @SDK.method
  @abstractmethod
  async def venue(self, id: str, /) -> TradingVenue:
    """Fetch a venue by ID."""

  @SDK.method
  @abstractmethod
  async def venues(self) -> Sequence[str]:
    """List supported all venues."""

  @SDK.method
  async def exchange(self, id: str, /) -> Exchange:
    """Fetch an exchange by ID.
    
    - `id`: `<venue_id>:<exchange_id>`
    """
    venue_id, exchange_id = id.split(':', 1)
    venue = await self.venue(venue_id)
    return await venue.exchange(exchange_id)

  @SDK.method
  async def perp_exchange(self, id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID.
    
    - `id`: `<venue_id>:<exchange_id>`
    """
    venue_id, exchange_id = id.split(':', 1)
    venue = await self.venue(venue_id)
    return await venue.perp_exchange(exchange_id)

  @SDK.method
  async def market(self, id: str, /) -> Market:
    """Fetch a market by ID.
    
    - `market_id`: `<venue_id>:<exchange_id>:<market_id>`
    """
    venue_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(venue_id)
    exchange = await venue.exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def perp_market(self, id: str, /):
    """Fetch a perpetual market by ID.
    
    - `market_id`: `<venue_id>:<exchange_id>:<market_id>`
    """
    venue_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(venue_id)
    exchange = await venue.perp_exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def depth(self, market_id: str, /) -> Book:
    """Fetch the market order book."""
    market = await self.market(market_id)
    return await market.depth()

  @SDK.method
  async def depth_stream(self, market_id: str, /):
    """Subscribe to the market order book."""
    market = await self.market(market_id)
    return await market.depth_stream()
  
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
  async def trades_stream(self, market_id: str, /) -> AsyncIterable[Trade]:
    """Subscribe to your real-time trades."""
    market = await self.market(market_id)
    return await market.trades_stream()

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


  @SDK.method
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
    market = await self.perp_market(market_id)
    return await market.perp_position()

  @SDK.method
  async def index(self, market_id: str, /):
    """Fetch the market index price."""
    market = await self.perp_market(market_id)
    return await market.index()
  
  @SDK.method
  async def next_funding(self, market_id: str, /) -> FundingRate:
    """Fetch the next funding rate and time."""
    market = await self.perp_market(market_id)
    return await market.next_funding()

  @SDK.method
  @PaginatedResponse.lift
  async def funding_history(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]:
    """Fetch perpetual funding rate history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_history(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch your funding payments history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page
