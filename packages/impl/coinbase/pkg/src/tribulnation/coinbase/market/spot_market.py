"""One Coinbase Advanced Trade spot market."""

from typing_extensions import AsyncContextManager, AsyncIterable, Any, Sequence
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

from . import impl


@dataclass(frozen=True, kw_only=True)
class SpotMarket(impl.MarketMixin, Market):
  """A spot pair on Coinbase Advanced Trade, e.g. `BTC-USD`."""

  CANDLE_INTERVALS = impl.CANDLE_INTERVALS

  @property
  def exchange_id(self) -> str:
    return impl.SPOT_EXCHANGE_ID

  async def depth(self, *, levels: int | None = None) -> Book:
    return await impl.depth(self, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    return impl.depth_stream(
      self, levels=levels, queue_size=queue_size, overflow=overflow
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    return await impl.rules(self, 'spot', refetch=refetch)

  def candles(
    self,
    interval: CandleInterval,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> PaginatedResponse[Candle]:
    self.check_interval(interval)
    return PaginatedResponse(impl.candles(self, interval, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    return await impl.open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(impl.trades_history(self, start, end))

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return impl.trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def position(self) -> Position:
    return await impl.position(self)

  async def collateral(self) -> Collateral:
    return await impl.collateral(self)

  async def available_notional(self) -> Decimal:
    return (await impl.collateral(self)).free_collateral

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    return await impl.place_order(self, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    return await impl.cancel_order(self, id, settings=settings)
