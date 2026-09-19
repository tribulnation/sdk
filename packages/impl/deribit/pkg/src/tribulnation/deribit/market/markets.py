"""Public Deribit spot and linear perpetual Market objects."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing_extensions import AsyncContextManager, AsyncIterable, Never, Sequence
from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  Collateral,
  FundingPayment,
  FundingRate,
  Market,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket,
  PerpPosition,
  Position,
  Rules,
  Settings,
  Trade,
)
from . import books
from .common import Public
from .candles import CANDLE_INTERVALS, candles


@dataclass(frozen=True, kw_only=True)
class SpotMarket(Public, Market):
  """Spot public data with explicit unsupported account methods."""

  symbol: str

  @property
  def market_id(self) -> str:
    """Return the unmodified native instrument name."""
    return self.symbol

  @property
  def exchange_id(self) -> str:
    """Spot's explicit product identity."""
    return 'spot'

  async def depth(self, *, levels: int | None = None) -> Book:
    """Read up to one hundred levels in base units."""
    return await books.depth(self.shared, self.symbol, levels=levels)

  def depth_stream(
    self,
    *,
    levels: int | None = None,
    queue_size: int = 1,
    overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    """Subscribe to up to twenty levels of native full snapshots."""
    return books.depth_stream(
      self.shared, self.symbol, levels=levels, queue_size=queue_size, overflow=overflow
    )

  async def rules(self, *, refetch: bool = False) -> Rules:
    """Unqualified fee denomination and quantity-step semantics are not guessed."""
    raise NotImplementedError('Deribit public rules are not qualified')

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Routed spot does not serve a native Deribit trade-candle series."""
    self.check_candles(interval, start, end)
    raise NotImplementedError('Deribit does not serve candles for Coinbase-routed spot')

  async def query_order(self, id: str) -> OrderState | None:
    """Order queries are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def open_orders(self) -> Sequence[OrderState]:
    """Open orders are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    """Private fills are outside this public Market implementation."""
    raise NotImplementedError(
      'Deribit Market supports public data only; use Report for account reporting'
    )

  def trades_stream(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    """Private fill streams are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def position(self) -> Position:
    """Private positions are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def collateral(self) -> Collateral:
    """Private collateral is outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def available_notional(self) -> Decimal:
    """Account buying power is outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    """This adapter does not place orders."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Never:
    """This adapter does not cancel orders."""
    raise NotImplementedError('Deribit Market supports public data only')


@dataclass(frozen=True, kw_only=True)
class NativeSpotMarket(SpotMarket):
  """Spot matched on Deribit, with native trade candles."""

  CANDLE_INTERVALS = CANDLE_INTERVALS

  def candles(
    self, interval: CandleInterval, start: datetime, end: datetime
  ) -> PaginatedResponse[Candle]:
    """Read the four qualified SDK intervals with aware half-open bounds."""
    self.check_candles(interval, start, end)
    return PaginatedResponse(candles(self.shared, self.symbol, interval, start, end))


@dataclass(frozen=True, kw_only=True)
class LinearPerpMarket(NativeSpotMarket, PerpMarket):
  """Native base-unit linear perpetual public data."""

  @property
  def exchange_id(self) -> str:
    """Linear perpetuals use the explicit perp product identity."""
    return 'perp'

  async def index(self, *, settings: Settings = {}) -> Decimal:
    """Read the native index price from the instrument ticker."""
    row = await self.shared.ticker(self.symbol)
    return Decimal(str(row['index_price']))

  async def next_funding(self) -> NextFunding:
    """Continuous accrual does not provide a qualified next-payment forecast."""
    raise NotImplementedError(
      'Deribit funding accrues continuously; no native next-payment forecast'
    )

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Hourly accrual observations are not mapped to discrete SDK payment times."""
    raise NotImplementedError(
      'Deribit hourly funding observations are not discrete payment rates'
    )

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    """Private funding payments are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def perp_position(self) -> PerpPosition:
    """Private positions are outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')

  async def perp_collateral(self) -> PerpCollateral:
    """Private collateral is outside the public Market surface."""
    raise NotImplementedError('Deribit Market supports public data only')
