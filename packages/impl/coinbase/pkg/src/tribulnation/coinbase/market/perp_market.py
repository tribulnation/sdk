"""One Coinbase INTX perpetual market."""

from typing_extensions import AsyncContextManager, AsyncIterable, Any, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy, PaginatedResponse
from tribulnation.sdk.market import (
  Book,
  Candle,
  CandleInterval,
  FundingPayment,
  FundingRate,
  NextFunding,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpMarket as _PerpMarket,
  PerpPosition,
  Rules,
  Settings,
  Trade,
)

from . import impl


@dataclass(frozen=True, kw_only=True)
class PerpMarket(impl.MarketMixin, _PerpMarket):
  """A perpetual swap on Coinbase International Exchange, e.g. `BTC-PERP-INTX`.

  Reached through the same Advanced Trade endpoints as spot. Positions and collateral
  additionally need a key scoped to an INTX portfolio; a retail `DEFAULT` key gets a
  live `PERMISSION_DENIED` from those two.
  """

  CANDLE_INTERVALS = impl.CANDLE_INTERVALS

  @property
  def exchange_id(self) -> str:
    return impl.INTX_EXCHANGE_ID

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
    return await impl.rules(self, 'intx', refetch=refetch)

  def candles(
    self,
    interval: CandleInterval,
    start: datetime,
    end: datetime,
  ) -> PaginatedResponse[Candle]:
    self.check_candles(interval, start, end)
    return PaginatedResponse(impl.candles(self, interval, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    return await impl.open_orders(self)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(impl.trades_history(self, start, end))

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail'
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return impl.trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def index(self, *, settings: Settings = {}) -> Decimal:
    return await impl.index(self)

  async def next_funding(self) -> NextFunding:
    return await impl.next_funding(self)

  def funding_rates(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> PaginatedResponse[FundingRate]:
    """Read public INTX settlement history with inclusive optional time bounds."""
    return PaginatedResponse(impl.funding_rates(self, start, end))

  def funding_payments(
    self, start: datetime, end: datetime
  ) -> PaginatedResponse[FundingPayment]:
    raise NotImplementedError(
      f'Coinbase exposes no funding-payment ledger for INTX perpetuals [{self.id}]; '
      '`futures.balance_summary.funding_pnl` is CFM dated-futures funding, not swap '
      'funding.'
    )

  async def perp_position(self) -> PerpPosition:
    return await impl.perp_position(self)

  async def perp_collateral(self) -> PerpCollateral:
    return await impl.perp_collateral(self)

  async def available_notional(self) -> Decimal:
    return (await impl.perp_collateral(self)).free_collateral

  async def place_order(
    self, order: Order, *, settings: Settings = {}
  ) -> OrderResponse:
    return await impl.place_order(self, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}) -> Any:
    return await impl.cancel_order(self, id, settings=settings)
