from typing_extensions import AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
import secrets

from tribulnation.sdk.core import PaginatedResponse, OverflowPolicy
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  Market,
  Book,
  Collateral,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Fees,
  Settings,
  Trade,
)

from tribulnation.hyperliquid.core import wrap_exceptions
from .impl.candles import CANDLE_INTERVALS, candles
from .impl.fees import personal_spot_fees

from .impl import (
  SpotMarketMixin,
  depth,
  depth_stream,
  spot_rules,
  open_orders,
  query_order,
  trades_history,
  trades_stream,
  spot_position,
  spot_market_collateral,
  place_order,
  cancel_order,
)


@dataclass(frozen=True, kw_only=True)
class SpotMarket(SpotMarketMixin, Market):
  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return f'{self.base_name}/{self.quote_name}:{self.asset_idx}'

  async def depth(self, *, levels: int | None = None, settings: Settings = {}) -> Book:
    """Fetch the REST book, shaped by `hyperliquid.depth_source` (see `Settings`)."""
    return await depth(self, levels=levels, settings=settings)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Stream the feed selected by `hyperliquid.depth_source` (see `Settings`)."""
    return depth_stream(
      self,
      levels=levels,
      queue_size=queue_size,
      overflow=overflow,
      settings=settings,
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    return await spot_rules(self, refetch=refetch)

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's spot rates for USDC- and USDE-quoted pairs; others are declined."""
    return await personal_spot_fees(self, refetch=refetch)

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    """Fetch trade candles in the requested half-open range."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self, interval, start, end))

  CANDLE_INTERVALS = CANDLE_INTERVALS

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
    settings: Settings = {},
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def position(self) -> Position:
    return await spot_position(self)

  async def collateral(self) -> Collateral:
    return await spot_market_collateral(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  @wrap_exceptions
  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  def random_client_order_id(self) -> str:
    """Generate a `cloid`: `0x` and 128 random bits as 32 hex digits."""
    return f'0x{secrets.token_hex(16)}'

  @wrap_exceptions
  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    return await place_order(self, order, settings=settings)

  @wrap_exceptions
  async def cancel_order(self, id: str, *, settings: Settings = {}):
    return await cancel_order(self, id, settings=settings)
