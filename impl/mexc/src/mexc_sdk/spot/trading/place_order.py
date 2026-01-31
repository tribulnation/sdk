from typing_extensions import Literal
from dataclasses import dataclass

from sdk.core import fmt_num
from sdk.market.trading.place_order import PlaceOrder as _PlaceOrder, Order as _Order, OrderState

from mexc.spot.trading.place_order import Order, LimitOrder, MarketOrder
from mexc_sdk.core import MarketMixin, wrap_exceptions
from ..user_data.query_order import query_order

def dump_order(order: _Order) -> Order:
  if order['type'] == 'LIMIT':
    return LimitOrder(
      type='LIMIT',
      side=order['side'],
      price=fmt_num(order['price']),
      quantity=fmt_num(order['qty'])
    )
  elif order['type'] == 'MARKET':
    return MarketOrder(
      type='MARKET',
      side=order['side'],
      quantity=fmt_num(order['qty'])
    )

@dataclass
class PlaceOrder(_PlaceOrder, MarketMixin):
  @wrap_exceptions
  async def _place_order(self, order: _Order, *, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    r = await self.client.spot.place_order(self.instrument, dump_order(order))
    if response == 'id':
      return r['orderId']
    else:
      return await query_order(self.client.spot, self.instrument, id=r['orderId'])
