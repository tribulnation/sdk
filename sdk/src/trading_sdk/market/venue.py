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
from .market import Market, PerpMarket
from .exchange import Exchange, PerpExchange

class ExchangeDescription(TypedDict):
  id: str
  type: Literal['spot', 'perp']

class TradingVenue(SDK):
  """An abstract multi-exchange venue interface."""
  ExchangeDescription = ExchangeDescription

  @property
  @abstractmethod
  def venue_id(self) -> str:
    ...

  @property
  def id(self) -> str:
    return self.venue_id
  
  @SDK.method
  @abstractmethod
  async def exchange(self, exchange_id: str, /) -> Exchange:
    """Fetch an exchange by ID."""

  @SDK.method
  @abstractmethod
  async def exchanges(self) -> Sequence[ExchangeDescription]:
    """List available exchanges."""

  async def market(self, exchange_market_id: str, /) -> Market:
    """Fetch a market by ID.
    
    - `exchange_market_id`: `<exchange_id>:<market_id>`
    """
    exchange_id, market_id = exchange_market_id.split(':', 1)
    exchange = await self.exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def depth(self, market_id: str, /, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""
    market = await self.market(market_id)
    return await market.depth(levels=levels)

  @SDK.method
  async def depth_stream(self, market_id: str, /, *, levels: int | None = None):
    """Subscribe to the market order book."""
    market = await self.market(market_id)
    return await market.depth_stream(levels=levels)
  
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
  async def available_notional(self, market_id: str, /):
    """Fetch the max. notional position you can open.
    
    - For spot, returns the free quote token balance
    - For futures, returns the available collateral times the maximum leverage
    """
    market = await self.market(market_id)
    return await market.available_notional()

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
  async def perp_exchange(self, exchange_id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID."""
    raise NotImplementedError(f'Perp exchanges are not supported by this venue [{self.id}].')

  @SDK.method
  async def perp_market(self, exchange_market_id: str, /) -> PerpMarket:
    """Fetch a market by ID.
    
    - `exchange_market_id`: `<exchange_id>:<market_id>`
    """
    exchange_id, market_id = exchange_market_id.split(':', 1)
    exchange = await self.perp_exchange(exchange_id)
    return await exchange.market(market_id)

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
  async def funding_history(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch perpetual funding rate history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_history(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(self, market_id: str, /, start: datetime, end: datetime):
    """Fetch your funding payments history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page

  @SDK.method
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
    market = await self.perp_market(market_id)
    return await market.perp_position()
