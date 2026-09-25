"""Single-market SDK views over Aster's shared exchange mappings."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing_extensions import (
  Any,
  AsyncContextManager,
  AsyncIterable,
  ClassVar,
  Iterable,
  Sequence,
)
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Fees,
  FundingPayment,
  FundingRate,
  Market as SDKMarket,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket as SDKPerpMarket,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)
from .perp import PerpExchange
from .spot import SpotExchange


@dataclass(frozen=True, kw_only=True)
class SpotMarket(SDKMarket):
  """Forward a selected native symbol without creating or owning another client."""

  exchange: SpotExchange | PerpExchange
  symbol: str
  CANDLE_INTERVALS: ClassVar[frozenset[CandleInterval]] = frozenset(
    ('1m', '5m', '15m', '1h', '4h', '1d')
  )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Allow direct market contexts to acquire the same shared owner."""
    yield self.shared

  @property
  def shared(self):
    """The client's sole resource owner."""
    return self.exchange.shared

  @property
  def venue_id(self) -> str:
    """The selected mainnet or testnet venue."""
    return self.exchange.venue_id

  @property
  def exchange_id(self) -> str:
    """The selected spot or perpetual exchange."""
    return self.exchange.exchange_id

  @property
  def market_id(self) -> str:
    """The native symbol, without asset-name translations."""
    return self.symbol

  async def depth(self, *, levels: int | None = None) -> Book:
    """Read a native REST book."""
    return await self.exchange.depth(self.symbol, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to the shared partial-depth stream."""
    return self.exchange.depth_stream(
      self.symbol, levels=levels, queue_size=queue_size, overflow=overflow
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Read native public trading filters."""
    return await self.exchange.rules(self.symbol, refetch=refetch)

  async def fees(self, *, refetch: bool = False) -> Fees:
    """Read the authenticated commission schedule."""
    return await self.exchange.fees(self.symbol, refetch=refetch)

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Page half-open native candle windows using SDK retry policies."""
    self.check_candles(interval, start, end)
    return self.exchange.candles(self.symbol, interval, start, end)

  async def query_order(self, id: str) -> OrderState | None:
    """Read a native order, or None for the documented not-found code."""
    return await self.exchange.query_order(self.symbol, id)

  async def open_orders(self) -> Sequence[OrderState]:
    """Read this market's currently active orders."""
    return await self.exchange.open_orders(self.symbol)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Fail explicitly until native history and pagination are qualified."""
    return self.exchange.trades_history(self.symbol, start, end)

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Read signed last-fill events with native fee assets."""
    return self.exchange.trades_stream(
      self.symbol, queue_size=queue_size, overflow=overflow
    )

  async def position(self) -> Position:
    """Read qualified perpetual positions; spot balances remain blocked."""
    return await self.exchange.position(self.symbol)

  async def collateral(self) -> Collateral:
    """Read qualified cross-margin collateral; spot balances remain blocked."""
    return await self.exchange.collateral(self.symbol)

  async def available_notional(self) -> Decimal:
    """Reject unsupported account-side capacity instead of estimating it."""
    return await self.exchange.available_notional(self.symbol)

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """Place a native MARKET, GTC or GTX order."""
    return await self.exchange.place_order(self.symbol, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    """Cancel one native order."""
    return await self.exchange.cancel_order(self.symbol, id, settings=settings)

  async def cancel_orders(self, ids: Sequence[str], *, settings: Settings = {}) -> Any:
    """Cancel in native batches of at most ten orders."""
    return await self.exchange.cancel_orders(self.symbol, ids, settings=settings)

  async def cancel_open_orders(self, *, settings: Settings = {}) -> Any:
    """Request cancellation of every open order on this symbol."""
    return await self.exchange.cancel_open_orders(self.symbol, settings=settings)


@dataclass(frozen=True, kw_only=True)
class PerpMarket(SpotMarket, SDKPerpMarket):
  """Add qualified perpetual funding and position reads to the common market view."""

  exchange: PerpExchange

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the venue's published index price."""
    return await self.exchange.index(self.symbol, settings=settings)

  async def next_funding(self) -> NextFunding:
    """Read the native next rate, settlement time and symbol-specific interval."""
    return await self.exchange.next_funding(self.symbol)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Page published funding settlements."""
    return self.exchange.funding_rates(self.symbol, start, end)

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Reject payment mapping until a nonzero sample is verified."""
    return self.exchange.funding_payments(self.symbol, start, end)

  async def perp_position(self) -> PerpPosition:
    """Read native one-way size and entry price."""
    return await self.exchange.perp_position(self.symbol)

  async def perp_collateral(self) -> PerpCollateral:
    """Reject the unsupported aggregate leverage figure."""
    return await self.exchange.perp_collateral(self.symbol)
