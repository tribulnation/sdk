from typing_extensions import Literal
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import fmt_num
from tribulnation.sdk.market.trading.place_order import PlaceOrder as _PlaceOrder, Order as _Order, OrderState

from mexc.spot.trading.place_order import Order, LimitOrder, MarketOrder
from mexc_sdk.core import MarketMixin, wrap_exceptions
from .query_order import query_order

def dump_order(order: _Order) -> Order:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  qty = fmt_num(abs(signed_qty))
  if order['type'] == 'LIMIT':
    return LimitOrder(
      type='LIMIT',
      side=side,
      price=fmt_num(order['price']),
      quantity=qty
    )
  elif order['type'] == 'MARKET':
    return MarketOrder(
      type='MARKET',
      side=side,
      quantity=qty
    )

@dataclass
class PlaceOrder(MarketMixin, _PlaceOrder):
  @wrap_exceptions
  async def _place_order_impl(self, order: _Order, *, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    r = await self.client.spot.place_order(self.instrument, dump_order(order))
    if response == 'id':
      return r['orderId']
    else:
      return await query_order(self.client.spot, self.instrument, id=r['orderId'])
