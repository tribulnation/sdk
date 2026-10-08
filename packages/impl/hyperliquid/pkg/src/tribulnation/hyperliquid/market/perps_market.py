from typing_extensions import AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import secrets

from tribulnation.sdk.core import PaginatedResponse, OverflowPolicy
from tribulnation.sdk.market import (
  Candle,
  CandleInterval,
  PerpMarket as _PerpMarket,
  Book,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Rules,
  Fees,
  Settings,
  Trade,
  FundingRate,
  NextFunding,
  FundingPayment,
)

from tribulnation.hyperliquid.core import wrap_exceptions
from .impl.candles import CANDLE_INTERVALS, candles
from .impl.fees import personal_perp_fees

from .impl import (
  PerpMarketMixin,
  depth,
  depth_stream,
  perps_rules,
  index,
  next_funding,
  funding_rates,
  funding_payments,
  perps_position,
  perp_market_collateral,
  perp_leverage,
  perp_available_notional,
  open_orders,
  place_order,
  cancel_order,
  query_order,
  trades_history,
  trades_stream,
)


@dataclass(frozen=True, kw_only=True)
class PerpMarket(PerpMarketMixin, _PerpMarket):
  @property
  def exchange_id(self) -> str:
    return self.dex_name or ''

  @property
  def market_id(self) -> str:
    return self.asset_name

  @wrap_exceptions
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

  @wrap_exceptions
  async def rules(self, *, refetch: bool = False) -> Rules:
    return await perps_rules(self, refetch=refetch)

  @PaginatedResponse.lift
  def trades_history(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Trade]]:
    return trades_history(self, start, end)

  async def fees(self, *, refetch: bool = False) -> Fees:
    """The account's rates for USDC-collateral perpetuals, HIP-3 included."""
    return await personal_perp_fees(self, refetch=refetch)

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
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def perp_position(self) -> PerpPosition:
    return await perps_position(self)

  async def perp_collateral(self) -> PerpCollateral:
    return await perp_market_collateral(self)

  async def leverage(self, *, refetch: bool = False) -> Decimal:
    """The account's `activeAssetData` leverage setting, capped at `maxLeverage`."""
    return await perp_leverage(self, refetch=refetch)

  async def available_notional(self) -> Decimal:
    """Free unified collateral times `leverage()`, for cross and isolated alike."""
    return await perp_available_notional(self)

  def random_client_order_id(self) -> str:
    """Generate a `cloid`: `0x` and 128 random bits as 32 hex digits."""
    return f'0x{secrets.token_hex(16)}'

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    return await place_order(self, order, settings=settings)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  async def cancel_order(self, id: str, *, settings: Settings = {}):
    return await cancel_order(self, id, settings=settings)

  async def index(self, *, settings: Settings = {}) -> Decimal:
    return await index(self, settings=settings)

  async def next_funding(self) -> NextFunding:
    return await next_funding(self)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    return PaginatedResponse(funding_rates(self, start, end))

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    return PaginatedResponse(funding_payments(self, start, end))
