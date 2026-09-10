from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  AsyncIterator,
  ClassVar,
  Sequence,
)
from abc import abstractmethod
from datetime import datetime
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import SDK, PaginatedResponse, OverflowPolicy
from .types import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  PerpCollateral,
  FundingRate,
  NextFunding,
  FundingPayment,
  Order,
  OrderResponse,
  OrderState,
  Position,
  PerpPosition,
  Trade,
  Rules,
  Fees,
)
from .settings import Settings


class Market(SDK):
  """An abstract market interface."""

  CANDLE_INTERVALS: ClassVar[frozenset[CandleInterval]] = frozenset()
  """Candle widths this market serves. Check it before calling `candles`; an interval
  outside it raises `ValueError` without a request being made."""

  @property
  def market_id(self) -> str: ...

  @property
  def exchange_id(self) -> str: ...

  @property
  def venue_id(self) -> str: ...

  @property
  def id(self) -> str:
    return f'{self.venue_id}:{self.exchange_id}:{self.market_id}'

  @SDK.method
  @abstractmethod
  async def depth(self, *, levels: int | None = None) -> Book:
    """Fetch the market order book."""

  @SDK.method
  @abstractmethod
  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    Venues fan out a shared upstream to each subscriber through a bounded queue:

    - `queue_size`: how many books to buffer for this subscriber.
    - `overflow`: what to do when the buffer is full. The default `'latest'`
      keeps only the newest book (a slow consumer skips stale books); pass
      `overflow='fail'` with a larger `queue_size` to capture every book
      instead (e.g. to record a full depth history).
    """

  @SDK.method
  @abstractmethod
  async def rules(self, *, refetch: bool = False) -> Rules:
    """Fetch market specifications and standard rates, without account-fee reads.

    - `refetch`: if `True`, fetch the rules even if they are already cached.
    """

  @SDK.method
  async def fees(self, *, refetch: bool = False) -> Fees:
    """Fetch combined account rates for maker/taker buys and sells.

    Includes applicable side and market adjustments, but excludes optional
    fee-payment discounts. Never falls back to standard or partial base rates.
    Unsupported implementations raise `NotImplementedError`. Authentication
    failures and missing account rates propagate instead of returning zero.
    """
    raise NotImplementedError(f'Account trading fees are not implemented: {self.id}')

  @SDK.method
  async def query_order(self, id: str) -> OrderState | None:
    """Fetch the state of the order with the given ID."""
    open_orders = await self.open_orders()
    for order in open_orders:
      if order.id == id:
        return order

  def check_interval(self, interval: CandleInterval):
    """Raise `ValueError` unless `interval` is one of `CANDLE_INTERVALS`."""
    if interval not in self.CANDLE_INTERVALS:
      served = ', '.join(sorted(self.CANDLE_INTERVALS)) or 'none'
      raise ValueError(
        f'{interval!r} candles are not served by this market [{self.id}]; '
        f'CANDLE_INTERVALS: {served}.'
      )

  def check_candles(self, interval: CandleInterval, start: datetime, end: datetime):
    """Validate an interval and its explicit, timezone-aware candle bounds."""
    self.check_interval(interval)
    if start.utcoffset() is None or end.utcoffset() is None:
      raise ValueError('Candle bounds must be timezone-aware')
    if end < start:
      raise ValueError('Candle end must not precede start')

  @SDK.method
  @abstractmethod
  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch the market's historical trade candles.

    Each opening timestamp appears at most once. Ordering within and across pages
    follows the venue; page sizes are not fixed. Empty intervals are not filled in.

    Args:
      interval: Candle width. Must be one of `CANDLE_INTERVALS`, else `ValueError`.
      start: Inclusive lower bound on opening time, as a timezone-aware datetime.
      end: Exclusive upper bound on opening time, as a timezone-aware datetime.
        A returned candle can still be forming. Equal bounds produce no candles.
    """

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
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
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
  @abstractmethod
  async def collateral(self) -> Collateral:
    """Fetch the collateral bucket backing this market."""

  @SDK.method
  @abstractmethod
  async def available_notional(self) -> Decimal:
    """Fetch the max. notional position you can open.

    - For spot, returns the free quote token balance
    - For futures, returns the available collateral times the maximum leverage
    """

  @SDK.method
  @abstractmethod
  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
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
  async def place_orders(
    self, orders: Sequence[Order], *, settings: Settings = {}
  ) -> Sequence[OrderResponse]:
    """Place multiple orders in the market."""
    return await asyncio.gather(
      *[self.place_order(order, settings=settings) for order in orders]
    )

  @SDK.method
  @abstractmethod
  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel an order in the market."""

  @SDK.method
  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel multiple orders in the market."""
    return await asyncio.gather(
      *[self.cancel_order(id, settings=settings) for id in ids]
    )

  @SDK.method
  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Cancel all open orders in the market."""
    open_orders = await self.open_orders()
    return await self.cancel_orders(
      [order.id for order in open_orders], settings=settings
    )


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
  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Fetch the market's historical funding rates.

    Args:
      start: Start of the window (inclusive). `None` fetches from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """

  @SDK.method
  @abstractmethod
  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
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
  @abstractmethod
  async def perp_collateral(self) -> PerpCollateral:
    """Fetch the perpetual collateral bucket backing this market."""
