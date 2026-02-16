from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.core import ValidationError, fmt_num
from tribulnation.sdk.market.trade import Place as _Place

from mexc.spot.trading.place_order import Order, LimitOrder, MarketOrder
from mexc_sdk.core import SpotMixin, StreamsMixin, wrap_exceptions

def dump_order(order: _Place.Order) -> Order:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  qty = fmt_num(abs(signed_qty))
  match order['type']:
    case 'LIMIT':
      return LimitOrder(
        type='LIMIT',
        side=side,
        price=fmt_num(order['price']),
        quantity=qty
      )
    case 'POST_ONLY':
      return LimitOrder(
        type='LIMIT_MAKER',
        side=side,
        price=fmt_num(order['price']),
        quantity=qty
      )
    case 'MARKET':
      return MarketOrder(
        type='MARKET',
        side=side,
        quantity=qty
      )
    case other:
      raise ValidationError(f'Unknown order type: {other}')

@dataclass
class Place(SpotMixin, StreamsMixin, _Place):
  @wrap_exceptions
  async def order(self, order: _Place.Order) -> _Place.Result:
    r = await self.client.spot.place_order(self.instrument, dump_order(order))
    return _Place.Result(id=r['orderId'], details=r)