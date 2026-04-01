from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_sdk.core import Stream, PaginatedResponse, LogicError
from trading_sdk.market import (
  Market,
  Book,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Trade,
)

from hyperliquid_sdk.core import wrap_exceptions

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
  place_order,
  cancel_order,
)


@dataclass(frozen=True, kw_only=True)
class SpotMarket(SpotMarketMixin, Market):
  @property
  def venue_id(self) -> str:
    return 'hyperliquid'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return f'{self.base_name}/{self.quote_name}:{self.asset_idx}'

  async def depth(self) -> Book:
    return await depth(self)

  async def depth_stream(self) -> Stream[Book]:
    return await depth_stream(self)

  async def rules(self, *, refetch: bool = False) -> Rules:
    return await spot_rules(self, refetch=refetch)

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  async def trades_stream(self) -> Stream[Trade]:
    return await trades_stream(self)

  async def position(self) -> Position:
    return await spot_position(self)

  @wrap_exceptions
  async def available_notional(self) -> Decimal:
    state = await self.client.info.spot_clearinghouse_state(self.address)
    for balance in state['balances']:
      if balance['token'] == self.quote_meta['index']:
        if balance['coin'] != self.quote_meta['name']:
          raise LogicError(f'Found balance with matching index {balance["token"]}, but wrong coin "{balance["coin"]}" != "{self.quote_name}"')
        total = Decimal(balance['total'])
        locked = Decimal(balance['hold'])
        return total - locked
    return Decimal(0)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  @wrap_exceptions
  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  @wrap_exceptions
  async def place_order(self, order: Order) -> OrderResponse:
    return await place_order(self, order)

  @wrap_exceptions
  async def cancel_order(self, id: str):
    return await cancel_order(self, id)

