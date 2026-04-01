from typing_extensions import Any, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import asyncio

from trading_sdk.core import Stream, PaginatedResponse
from trading_sdk.market import (
  Book,
  FundingPayment,
  FundingRate,
  Order,
  OrderResponse,
  OrderState,
  PerpMarket,
  PerpPosition,
  Rules,
  Trade,
)

from dydx_sdk.core import wrap_exceptions
from .impl import  (
  MarketMixin,
  max_leverage,
  parse_book,
  trades_history,
  trades_stream,
  next_funding,
  funding_history,
  funding_payments,
  open_orders,
  place_order,
  place_orders,
  query_order,
  cancel_order,
  cancel_orders,
)

@dataclass(frozen=True)
class Market(MarketMixin, PerpMarket):

  @property
  def market_id(self) -> str:
    return self.market

  @property
  def exchange_id(self) -> str:
    return 'perp'

  @property
  def venue_id(self) -> str:
    return 'dydx'

  @wrap_exceptions
  async def depth(self) -> Book:
    book = await self.indexer.data.get_order_book(self.market)
    return parse_book(book)

  async def depth_stream(self) -> Stream[Book]:
    return await self.subscribe_depth(self.market)
    
  async def rules(self, *, refetch: bool = False) -> Rules:
    return await self.shared.rules(self.market, refetch=refetch)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  async def trades_stream(self) -> Stream[Trade]:
    return await trades_stream(self)

  @wrap_exceptions
  async def perp_position(self) -> PerpPosition:
    positions = await self.indexer.data.list_parent_positions(
      await self.address,
      parent_subaccount=self.settings.get('parent_subaccount', 0),
    )
    market_positions = [
      p for p in positions
      if p['market'] == self.market and p['status'] == 'OPEN'
    ]
    if not market_positions:
      return PerpPosition()

    for p in market_positions:
      assert (
        (Decimal(p['size']) > 0 and p['side'] == 'LONG') or
        (Decimal(p['size']) < 0 and p['side'] == 'SHORT')
      )

    signed_sizes = [
      Decimal(p['size'])
      for p in market_positions
    ]
    net_size = sum(signed_sizes, Decimal(0))
    if net_size == 0:
      return PerpPosition()

    total_notional = sum(
      Decimal(p['size']) * Decimal(p['entryPrice'])
      for p in market_positions
    )
    total_size = sum(Decimal(p['size']) for p in market_positions)
    avg_entry = total_notional / total_size if total_size != 0 else Decimal(0)

    return PerpPosition(size=net_size, entry_price=avg_entry)

  @wrap_exceptions
  async def available_notional(self) -> Decimal:
    address = await self.address
    sub, market = await asyncio.gather(
      self.indexer.data.get_subaccount(address=await self.address, subaccount=self.subaccount),
      self.indexer.data.get_market(self.market)
    )
    collateral = Decimal(sub['subaccount']['freeCollateral'])
    leverage = max_leverage(market)
    return collateral*leverage

  async def place_order(self, order: Order) -> OrderResponse:
    return await place_order(self, order)

  async def place_orders(self, orders: Sequence[Order]) -> Sequence[OrderResponse]:
    return await place_orders(self, orders)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  async def cancel_order(self, id: str) -> Any:
    return await cancel_order(self, id)

  async def cancel_orders(self, ids: Sequence[str]) -> Any:
    return await cancel_orders(self, ids)

  @wrap_exceptions
  async def index(self) -> Decimal:
    market = await self.indexer.data.get_market(self.market)
    return Decimal(market['oraclePrice'])

  async def next_funding(self) -> FundingRate:
    return await next_funding(self)

  def funding_history(self, start: datetime, end: datetime) -> PaginatedResponse[FundingRate]:
    return PaginatedResponse(funding_history(self, start, end))

  def funding_payments(self, start: datetime, end: datetime) -> PaginatedResponse[FundingPayment]:
    return PaginatedResponse(funding_payments(self, start, end))
