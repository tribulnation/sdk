from typing_extensions import AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.core import Stream, PaginatedResponse
from trading_sdk.market import (
  PerpMarket as _PerpMarket,
  Book,
  Order,
  OrderResponse,
  OrderState,
  PerpPosition,
  Rules,
  Trade,
  FundingRate,
  FundingPayment,
)

from hyperliquid_sdk.core import wrap_exceptions

from .impl import (
  PerpMarketMixin,
  depth,
  depth_stream,
  perps_rules,
  index,
  next_funding,
  funding_history,
  funding_payments,
  perps_position,
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
    return "perp"

  @property
  def market_id(self) -> str:
    return self.asset_name

  @wrap_exceptions
  async def depth(self) -> Book:
    return await depth(self)

  async def depth_stream(self) -> Stream[Book]:
    return await depth_stream(self)

  @wrap_exceptions
  async def rules(self, *, refetch: bool = False) -> Rules:
    return await perps_rules(self, refetch=refetch)

  @PaginatedResponse.lift
  def trades_history(self, start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]:
    return trades_history(self, start, end)

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  async def trades_stream(self) -> Stream[Trade]:
    return await trades_stream(self)

  @wrap_exceptions
  async def perp_position(self) -> PerpPosition:
    return await perps_position(self)

  async def place_order(self, order: Order) -> OrderResponse:
    return await place_order(self, order)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  async def cancel_order(self, id: str):
    return await cancel_order(self, id)

  @wrap_exceptions
  async def index(self) -> Decimal:
    return await index(self)

  async def next_funding(self) -> FundingRate:
    return await next_funding(self)

  def funding_history(self, start: datetime, end: datetime) -> PaginatedResponse[FundingRate]:
    return PaginatedResponse(funding_history(self, start, end))

  def funding_payments(self, start: datetime, end: datetime) -> PaginatedResponse[FundingPayment]:
    return PaginatedResponse(funding_payments(self, start, end))

