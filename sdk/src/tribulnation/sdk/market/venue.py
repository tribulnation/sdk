from typing_extensions import Any, AsyncIterable, AsyncIterator, Sequence, Literal, TypedDict
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
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
from .exchange import Exchange, PerpExchange

class ExchangeDescription(TypedDict):
  id: str
  type: Literal['spot', 'perp']

class TradingVenue(SDK):
  """An abstract multi-exchange venue interface."""
  ExchangeDescription = ExchangeDescription

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...

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
  @asynccontextmanager
  async def depth_stream(
    self, market_id: str, /, *, levels: int | None = None,
    queue_size: int = 1, overflow: OverflowPolicy = 'latest',
  ) -> AsyncIterator[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    See `Market.depth_stream` for `queue_size`/`overflow` (e.g. `overflow='fail'`
    with a larger `queue_size` to capture every book).
    """
    market = await self.market(market_id)
    async with market.depth_stream(levels=levels, queue_size=queue_size, overflow=overflow) as stream:
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
  @asynccontextmanager
  async def trades_stream(
    self, market_id: str, /, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail',
  ) -> AsyncIterator[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades.

    See `Market.trades_stream` for `queue_size`/`overflow`.
    """
    market = await self.market(market_id)
    async with market.trades_stream(queue_size=queue_size, overflow=overflow) as stream:
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
    """Place an order in the market.

    See ``Market.place_order`` for SDK order type semantics.
    """
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
  async def next_funding(self, market_id: str, /) -> NextFunding:
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
