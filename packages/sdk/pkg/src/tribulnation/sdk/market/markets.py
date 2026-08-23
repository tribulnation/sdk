from typing_extensions import Any, AsyncIterable, AsyncIterator, Sequence, Literal, TypedDict
from abc import abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
from .types import (
  Book,
  Collateral, PerpCollateral,
  FundingRate, NextFunding, FundingPayment,
  Order, OrderResponse, OrderState,
  Position, PerpPosition,
  Trade,
  Rules,
)
from .settings import Settings
from .market import Market
from .exchange import Exchange, PerpExchange
from .venue import TradingVenue

class TradingMarkets(SDK):
  """A collection of all venues supported by the SDK."""

  @SDK.method
  @abstractmethod
  async def venue(self, id: str, /) -> TradingVenue:
    """Fetch a venue by account ID."""

  @SDK.method
  @abstractmethod
  async def venues(self) -> Sequence[str]:
    """List configured account IDs."""

  @SDK.method
  async def exchange(self, id: str, /) -> Exchange:
    """Fetch an exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    account_id, exchange_id = id.split(':', 1)
    venue = await self.venue(account_id)
    return await venue.exchange(exchange_id)

  @SDK.method
  async def perp_exchange(self, id: str, /) -> PerpExchange:
    """Fetch a perpetual exchange by ID.

    - `id`: `<account_id>:<exchange_id>`
    """
    account_id, exchange_id = id.split(':', 1)
    venue = await self.venue(account_id)
    return await venue.perp_exchange(exchange_id)

  @SDK.method
  async def market(self, id: str, /) -> Market:
    """Fetch a market by ID.

    - `market_id`: `<account_id>:<exchange_id>:<market_id>`
    """
    account_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(account_id)
    exchange = await venue.exchange(exchange_id)
    return await exchange.market(market_id)

  @SDK.method
  async def perp_market(self, id: str, /):
    """Fetch a perpetual market by ID.

    - `market_id`: `<account_id>:<exchange_id>:<market_id>`
    """
    account_id, exchange_id, market_id = id.split(':', 2)
    venue = await self.venue(account_id)
    exchange = await venue.perp_exchange(exchange_id)
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
  async def collateral(self, id: str, /) -> Collateral:
    """Fetch collateral.

    - 2-segment (`dydx:perp`): exchange-level bucket.
    - 3-segment (`dydx:perp:BTC-USD`): market-level (mode-aware).
    """
    parts = id.split(':', 2)
    if len(parts) == 3:
      account_id, exchange_id, market_id = parts
      venue = await self.venue(account_id)
      exchange = await venue.exchange(exchange_id)
      return await exchange.collateral(market_id)
    account_id, exchange_id = parts
    venue = await self.venue(account_id)
    exchange = await venue.exchange(exchange_id)
    return await exchange.collateral()

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
  async def perp_position(self, market_id: str, /) -> PerpPosition:
    """Fetch your open position in the perpetual market."""
    market = await self.perp_market(market_id)
    return await market.perp_position()

  @SDK.method
  async def perp_collateral(self, id: str, /) -> PerpCollateral:
    """Fetch perpetual collateral.

    - 2-segment (`dydx:perp`): exchange-level bucket.
    - 3-segment (`dydx:perp:BTC-USD`): market-level (mode-aware).
    """
    parts = id.split(':', 2)
    if len(parts) == 3:
      account_id, exchange_id, market_id = parts
      venue = await self.venue(account_id)
      exchange = await venue.perp_exchange(exchange_id)
      return await exchange.perp_collateral(market_id)
    account_id, exchange_id = parts
    venue = await self.venue(account_id)
    exchange = await venue.perp_exchange(exchange_id)
    return await exchange.perp_collateral()

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
  async def funding_rates(self, market_id: str, /, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Sequence[FundingRate]]:
    """Fetch the market's historical funding rates.

    Args:
      market_id: Market to fetch rates for.
      start: Start of the window (inclusive). `None` fetches from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """
    market = await self.perp_market(market_id)
    async for page in market.funding_rates(start, end):
      yield page

  @SDK.method
  @PaginatedResponse.lift
  async def funding_payments(self, market_id: str, /, start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]:
    """Fetch your funding payments history."""
    market = await self.perp_market(market_id)
    async for page in market.funding_payments(start, end):
      yield page
