from typing_extensions import Any, AsyncContextManager, AsyncIterable, AsyncIterator, Sequence
from abc import abstractmethod
from datetime import datetime
from decimal import Decimal
import asyncio

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
  def depth_stream(
    self, *, levels: int | None = None,
    queue_size: int = 1, overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    Venues fan out a shared upstream to each subscriber through a bounded queue:

    - `queue_size`: how many books to buffer for this subscriber.
    - `overflow`: what to do when the buffer is full. The default `'latest'`
      keeps only the newest book (a slow consumer skips stale books); pass
      `overflow='fail'` with a larger `queue_size` to capture every book
      instead (e.g. to record a full depth history).

    `queue_size`/`overflow` are ignored by this polling default, which has no
    shared upstream to fan out; venue subscriptions honor them.
    """
    ...

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
  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades.

    Venues fan out a shared upstream to each subscriber through a bounded queue:

    - `queue_size`: how many trades to buffer for this subscriber.
    - `overflow`: what to do when the buffer is full. The default `'fail'` fails
      the subscriber with a `NetworkError` (so the caller can reconnect) rather
      than dropping trades silently; `'latest'` keeps only the newest instead.
    """

  @SDK.method
  @abstractmethod
  async def position(self) -> Position:
    """Fetch your open position in the market."""

  @SDK.method
  async def collateral(self) -> Collateral:
    """Fetch the collateral bucket backing this market."""
    raise NotImplementedError(f'Collateral is not supported by this market [{self.id}].')

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
    """Place an order in the market.

    ``order["qty"]`` is signed in base units: positive buys and negative sells.
    ``order["price"]`` is always required by the SDK order shape.

    Order type semantics:

    - ``"LIMIT"`` places a normal limit order at ``price``. It may rest on the
      book unless venue settings request a different time-in-force.
    - ``"POST_ONLY"`` places a maker-only limit order at ``price``. The venue
      should reject or cancel it rather than taking liquidity.
    - ``"MARKET"`` means immediate execution with price protection. The SDK
      passes ``price`` as the worst acceptable limit price: for buys, the maximum
      price to pay; for sells, the minimum price to accept. Venues with native
      market orders may ignore ``price``; venues without native market orders
      should implement this as an aggressive non-resting limit order, preferably
      IOC. A market order may partially fill unless venue/settings semantics are
      stricter, such as FOK.

    Venue-specific ``settings`` may refine time-in-force, reduce-only, expiry,
    or other execution flags. If a venue cannot support the requested semantics,
    it should raise an API/validation error rather than silently placing a
    materially different order.
    """

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
  def funding_rates(self, start: datetime | None = None, end: datetime | None = None) -> PaginatedResponse[FundingRate]:
    """Fetch the market's historical funding rates.

    Args:
      start: Start of the window (inclusive). `None` fetches from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """

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

  @SDK.method
  async def collateral(self) -> Collateral:
    """Fetch the collateral bucket backing this market."""
    return await self.perp_collateral()

  @SDK.method
  async def perp_collateral(self) -> PerpCollateral:
    """Fetch the perpetual collateral bucket backing this market."""
    raise NotImplementedError(f'Collateral is not supported by this market [{self.id}].')
