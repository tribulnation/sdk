"""One Kraken Spot market."""

from typing_extensions import Any, AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  Market,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

from .impl import (
  MarketMixin,
  available_notional,
  collateral,
  depth,
  depth_stream,
  open_orders,
  position,
  rules,
  trades_history,
  trades_stream,
)
from .impl.candles import CANDLE_INTERVALS, candles


@dataclass(frozen=True, kw_only=True)
class SpotMarket(MarketMixin, Market):
  """Kraken implementation of `Market`, for one Spot pair.

  Order placement and cancellation are deliberately unimplemented: this package
  reads Kraken, it does not trade on it.
  """

  @property
  def venue_id(self) -> str:
    return 'kraken'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.altname

  async def depth(self, *, levels: int | None = None) -> Book:
    return await depth(self, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    return depth_stream(self, levels=levels, queue_size=queue_size, overflow=overflow)

  async def rules(self, *, refetch: bool = False) -> Rules:
    return await rules(self, refetch=refetch)

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch the retained trade candles whose opens fall within the requested range."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self, interval, start, end))

  CANDLE_INTERVALS = CANDLE_INTERVALS

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def position(self) -> Position:
    return await position(self)

  async def collateral(self) -> Collateral:
    return await collateral(self)

  async def available_notional(self) -> Decimal:
    return await available_notional(self)

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    raise NotImplementedError(
      f'place_order is not implemented for this market [{self.id}]: '
      'tribulnation-kraken reads Kraken and does not trade on it.'
    )

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    raise NotImplementedError(
      f'cancel_order is not implemented for this market [{self.id}]: '
      'tribulnation-kraken reads Kraken and does not trade on it.'
    )
