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
from tribulnation.sdk.impl.accounts import VenueId
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


def open_trades_stream(
  market: 'Market',
  *,
  queue_size: int,
  overflow: OverflowPolicy,
  settings: Settings,
) -> AsyncContextManager[AsyncIterable[Trade]]:
  """Call `market.trades_stream`, passing `settings` only when there are any.

  Venue packages released before `trades_stream` took `settings` have no such
  parameter; leaving it out when empty keeps them working with this core until a caller
  actually asks for a venue option.
  """
  if not settings:
    return market.trades_stream(queue_size=queue_size, overflow=overflow)
  return market.trades_stream(
    queue_size=queue_size, overflow=overflow, settings=settings
  )


class Market(SDK):
  """An abstract market interface."""

  CANDLE_INTERVALS: ClassVar[frozenset[CandleInterval]] = frozenset()
  """Candle widths this market serves. Check it before calling `candles`; an interval
  outside it raises `ValueError` without a request being made."""

  @property
  def market_id(self) -> str:
    """Venue-native market ID, the last segment of `id`."""
    ...

  @property
  def exchange_id(self) -> str:
    """Exchange (product family) ID within the venue, e.g. `'spot'` or `'perp'`."""
    ...

  @property
  @abstractmethod
  def venue_id(self) -> VenueId:
    """The venue this object trades on, e.g. `'hyperliquid'` or `'dydx_testnet'`;
    never an account key."""

  @property
  @abstractmethod
  def account_id(self) -> str:
    """Key of the account this object was opened under: `'hl'` for
    `MarketSDK({'hl': accounts.Hyperliquid(...)})`. Objects built directly, outside a
    root SDK, default to their `venue_id`."""

  @property
  def id(self) -> str:
    """Full market ID, `<account_id>:<exchange_id>:<market_id>`, accepted by
    `TradingMarkets.market` on the root SDK that opened this market."""
    return f'{self.account_id}:{self.exchange_id}:{self.market_id}'

  @SDK.method
  @abstractmethod
  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """Fetch the market order book.

    - `levels`: cap the number of levels per side; `None` returns the full book.
    - `settings`: venue-specific options keyed by venue name; each venue reads only
      its own key and ignores the rest.
    """

  @SDK.method
  @abstractmethod
  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the market order book.

    Venues fan out a shared upstream to each subscriber through a bounded queue:

    - `levels`: cap the number of levels per side; `None` streams the full book.
      It trims whatever the feed delivers and never selects the feed.
    - `queue_size`: how many books to buffer for this subscriber.
    - `overflow`: what to do when the buffer is full. The default `'latest'`
      keeps only the newest book (a slow consumer skips stale books); pass
      `overflow='fail'` with a larger `queue_size` to capture every book
      instead (e.g. to record a full depth history).
    - `settings`: venue-specific options keyed by venue name, e.g.
      `{'hyperliquid': {'depth_source': 'bbo'}}` to choose a venue's depth feed.
      Each venue reads only its own key and ignores the rest. Different feeds are
      different streams and need not agree tick-for-tick.
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
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Subscribe to your real-time trades.

    Venues fan out a shared upstream to each subscriber through a bounded queue:

    - `queue_size`: how many trades to buffer for this subscriber.
    - `overflow`: what to do when the buffer is full. The default `'fail'` fails
      the subscriber with a `NetworkError` (so the caller can reconnect) rather
      than dropping trades silently; `'latest'` keeps only the newest instead.
    - `settings`: venue-specific options keyed by venue name, e.g.
      `{'dydx': {'trades_source': 'fastest'}}` to choose a venue's fill source.
      Each venue reads only its own key and ignores the rest.
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
  async def available_notional(self) -> Decimal:
    """Fetch the maximum notional position you can open right now.

    - Spot: the free quote-token balance. The default returns
      `collateral().free_collateral`, the free part of the quote bucket.
    - Perpetuals: the free collateral times the account's leverage on the market;
      see `PerpMarket.available_notional`.

    This is opening capacity, deliberately separate from `collateral()`, which is
    about liquidation distance. Venues may override it with a more precise figure.
    """
    return (await self.collateral()).free_collateral

  def random_client_order_id(self) -> str | None:
    """Generate a fresh client order ID in the form this market's `place_order` sends.

    Returns `None` where the market ignores client order IDs, so the result can go
    into `Order['client_order_id']` unchecked.
    """
    return None

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

    ``order["client_order_id"]`` is optional, and ``None`` means the same as
    leaving it out. Venues with native client order IDs send it unchanged, so a
    value breaking the venue's format or uniqueness rules raises the venue's
    error, and report it back on the order's fills as ``Trade.client_order_id``;
    ``random_client_order_id()`` generates a valid one. Venues without them ignore it:
    it identifies the order without changing how it executes.

    Venue-specific ``settings`` may refine time-in-force, reduce-only, expiry,
    or other execution flags. If a venue cannot support the requested semantics,
    it should raise an API/validation error rather than silently placing a
    materially different order.

    Raises:
      OrderRejected: The venue definitively refused the order: nothing rests and
        nothing filled, so it is safe to treat as dead (e.g. an IOC that could not
        match). Venues raise it only where their answer makes that certain.
      ApiError: Any other venue error. Unlike `OrderRejected`, it may be ambiguous
        (e.g. a 5xx): the order may have been placed.
      NetworkError: The venue could not be reached or the request timed out; the
        order may have been placed.
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
  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """Fetch the leverage this account can open at on this market.

    The multiple of free collateral the account can open as notional here: opening
    `n` of notional needs `n / leverage` of collateral. It is account-specific (for
    example a per-market leverage setting, or the venue's default for a market the
    account never configured), which is why it is neither part of the public
    `rules()` nor of `collateral()`. It is cached after the first call.

    Perpetual-only: spot markets trade on their cash balance, so the SDK defines no
    spot leverage. Unsupported implementations raise `NotImplementedError`.

    Args:
      refetch: Fetch again even if the leverage is already cached.
    """
    raise NotImplementedError(f'Account leverage is not implemented: {self.id}')

  @SDK.method
  async def available_notional(self) -> Decimal:
    """Fetch the maximum notional position you can open right now.

    The default is `collateral().free_collateral * leverage()`: the free part of the
    bucket backing this market (mode-aware) times the account's leverage on it. It
    raises `NotImplementedError` where either is unsupported. Venues override it
    when they publish a more precise figure, e.g. where an isolated position is
    funded from the cross pool rather than from its own bucket.
    """
    leverage = await self.leverage()
    return (await self.collateral()).free_collateral * leverage

  @SDK.method
  @abstractmethod
  async def perp_collateral(self) -> PerpCollateral:
    """Fetch the perpetual collateral bucket backing this market."""
