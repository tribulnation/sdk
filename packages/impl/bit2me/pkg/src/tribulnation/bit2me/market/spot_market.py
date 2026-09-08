"""One Bit2Me Trading Spot market."""

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
  cancel_order,
  collateral,
  depth,
  depth_stream,
  open_orders,
  place_order,
  position,
  query_order,
  rules,
  trades_history,
  trades_stream,
)


@dataclass(frozen=True, kw_only=True)
class SpotMarket(MarketMixin, Market):
  """Bit2Me implementation of `Market`, for one Trading Spot pair."""

  @property
  def venue_id(self) -> str:
    return 'bit2me'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.symbol

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
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> PaginatedResponse[Candle]:
    raise NotImplementedError(
      f'candles is not implemented for this market [{self.id}]: typed_bit2me types '
      '`v1.trading.candles` rows as `list[float]` and declares no paged walk for it, '
      'so neither the prices nor the sweep can come through the client.'
    )

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

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
    return await place_order(self, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    return await cancel_order(self, id, settings=settings)
