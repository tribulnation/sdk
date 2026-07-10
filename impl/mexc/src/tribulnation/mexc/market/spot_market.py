from typing_extensions import AsyncContextManager, AsyncIterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.core import PaginatedResponse
from tribulnation.sdk.market import (
  Market,
  Book,
  Order,
  OrderResponse,
  OrderState,
  Position,
  Rules,
  Settings,
  Trade,
)

from tribulnation.mexc.core.exc import wrap_exceptions
from .impl import (
  MarketMixin,
  depth,
  depth_stream,
  rules,
  open_orders,
  query_order,
  trades_history,
  trades_stream,
  position,
  place_order,
  cancel_order,
)

@dataclass(frozen=True, kw_only=True)
class SpotMarket(MarketMixin, Market):

  @property
  def venue_id(self) -> str:
    return 'mexc'

  @property
  def exchange_id(self) -> str:
    return 'spot'

  @property
  def market_id(self) -> str:
    return self.instrument

  async def depth(self, *, levels: int | None = None) -> Book:
    return await depth(self, levels=levels)

  def depth_stream(self, *, levels: int | None = None) -> AsyncContextManager[AsyncIterable[Book]]:
    return depth_stream(self, levels=levels)

  async def rules(self, *, refetch: bool = False) -> Rules:
    return await rules(self, refetch=refetch)

  async def open_orders(self) -> Sequence[OrderState]:
    return await open_orders(self)

  async def query_order(self, id: str) -> OrderState | None:
    return await query_order(self, id)

  def trades_history(self, start: datetime, end: datetime) -> PaginatedResponse[Trade]:
    return PaginatedResponse(trades_history(self, start, end))

  def trades_stream(self) -> AsyncContextManager[AsyncIterable[Trade]]:
    return trades_stream(self)

  async def position(self) -> Position:
    return await position(self)

  @wrap_exceptions
  async def available_notional(self):
    r = await self.client.spot.account.info(recv_window=self.shared.recv_window)
    for b in r.get('balances', []):
      if b.get('asset') == self.info.get('quoteAsset'):
        return Decimal(b.get('free') or '0')
    return Decimal(0)

  async def place_order(self, order: Order, *, settings: Settings = {}) -> OrderResponse:
    return await place_order(self, order, settings=settings)

  async def cancel_order(self, id: str, *, settings: Settings = {}):
    return await cancel_order(self, id, settings=settings)
