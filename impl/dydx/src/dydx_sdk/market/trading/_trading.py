from typing_extensions import Sequence, Literal
from dataclasses import dataclass

from tribulnation.sdk.core import SDK, ApiError
from tribulnation.sdk.market import Trading as _Trading
from tribulnation.sdk.market.types.order import OrderState, Order

from dydx_v4_client import OrderFlags
from dydx_sdk.core import MarketMixin, TradingMixin, UserDataMixin, wrap_exceptions
from .indexer import parse_state, parse_id, serialize_id
from .node import export_order

@dataclass
class Trading(MarketMixin, TradingMixin, UserDataMixin, _Trading):

  @SDK.method
  @wrap_exceptions
  async def _list_orders(self) -> list[OrderState]:
    orders = await self.indexer_data.list_orders(
      self.address, ticker=self.market, subaccount=self.subaccount,
      unsafe=True
    )
    return [parse_state(o, address=self.address) for o in orders]

  async def query_order(self, id: str) -> OrderState:
    orders = await self._list_orders()
    for o in orders:
      if o.id == id:
        return o
    raise ApiError(f'Order not found: {id}')

  async def open_orders(self) -> Sequence[OrderState]:
    orders = await self._list_orders()
    return [o for o in orders if o.active]


  @wrap_exceptions
  async def cancel_order(self, id: str) -> OrderState:
    order_id = parse_id(id)
    if order_id.order_flags == OrderFlags.LONG_TERM:
      await self.node.cancel_order(order_id, unsafe=True)
    # else it's a short term order, which gets automatically canceled
    return await self.query_order(id)


  async def _place_order_impl(
    self, order: Order, *,
    response: Literal['id', 'state'] = 'id'
  ) -> str | OrderState:
    market = await self.fetch_market(self.market)
    dydx_order = export_order(order, market, limit_flags=self.limit_flags, market_buffer=self.market_buffer)
    r = await self.node.place_order(market, dydx_order, unsafe=True)
    id = serialize_id(r['order'].order_id)
    if response == 'id':
      return id
    else:
      return await self.query_order(id)