from typing_extensions import AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import PaginatedResponse, LogicError, OverflowPolicy
from tribulnation.sdk.market import (
  PerpMarket as _PerpMarket,
  Book,
  Order,
  OrderResponse,
  OrderState,
  PerpCollateral,
  PerpPosition,
  Rules,
  Settings,
  Trade,
  FundingRate,
  NextFunding,
  FundingPayment,
)

from tribulnation.hyperliquid.core import wrap_exceptions

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
  def venue_id(self) -> str:
    return "hyperliquid"

  @property
  def exchange_id(self) -> str:
    return self.dex_name or ''

  @property
  def market_id(self) -> str:
    return self.asset_name

  @wrap_exceptions
  async def depth(self, *, levels: int | None = None) -> Book:
    return await depth(self)

  def depth_stream(
    self, *, levels: int | None = None,
    queue_size: int = 1, overflow: OverflowPolicy = 'latest',
  ) -> AsyncContextManager[AsyncIterable[Book]]:
    return depth_stream(self, queue_size=queue_size, overflow=overflow)

  @wrap_exceptions
  async def rules(self, *, refetch: bool = False) -> Rules:
    return await perps_rules(self, refetch=refetch)

  @PaginatedResponse.lift
  def trades_history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
    return trades_history(self, start, end)

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  def trades_stream(
    self, *, queue_size: int = 1000, overflow: OverflowPolicy = 'fail',
  ) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self, queue_size=queue_size, overflow=overflow)

  async def perp_position(self) -> PerpPosition:
    return await perps_position(self)

  async def perp_collateral(self) -> PerpCollateral:
    return await perp_market_collateral(self)

  @wrap_exceptions
  async def available_notional(self) -> Decimal:
    state = await self.client.info.spot_clearinghouse_state(self.address)
    for balance in state['balances']:
      if balance['token'] == self.collateral_meta['index']:
        if balance['coin'] != self.collateral_name:
          raise LogicError(f'Found balance with matching index {balance["token"]}, but wrong coin "{balance["coin"]}" != "{self.collateral_name}"')
        total = Decimal(balance['total'])
        locked = Decimal(balance['hold'])
        collateral = total - locked
        leverage = self.asset_meta['maxLeverage']
        return collateral * leverage

    return Decimal(0)

  async def place_order(self, order: Order, *, settings: Settings = {}) -> OrderResponse:
    return await place_order(self, order, settings=settings)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  async def cancel_order(self, id: str, *, settings: Settings = {}):
    return await cancel_order(self, id, settings=settings)

  async def index(self, *, settings: Settings = {}) -> Decimal:
    return await index(self, settings=settings)

  async def next_funding(self) -> NextFunding:
    return await next_funding(self)

  def funding_rates(self, start: datetime | None = None, end: datetime | None = None) -> PaginatedResponse[FundingRate]:
    return PaginatedResponse(funding_rates(self, start, end))

  def funding_payments(self, start: datetime, end: datetime) -> PaginatedResponse[FundingPayment]:
    return PaginatedResponse(funding_payments(self, start, end))
