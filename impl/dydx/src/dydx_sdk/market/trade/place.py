from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trade import Place as _Place
from tribulnation.sdk.core import ValidationError

from dydx.node.private.place_order import Order, TimeInForce, Flags
from dydx_sdk.core import TradingMixin, wrap_exceptions
from dydx_sdk.market.user.orders import serialize_id

def order_price(order: _Place.Order) -> Decimal:
  match order['type']:
    case 'LIMIT' | 'POST_ONLY':
      return Decimal(order['price'])
    case 'MARKET':
      return Decimal('1e12') if Decimal(order['qty']) > 0 else Decimal(0)
    case other:
      raise ValidationError(f'Unknown order type: {other}')

def time_in_force(order: _Place.Order, limit_flags: Flags) -> TimeInForce:
  match order['type']:
    case 'POST_ONLY':
      return 'POST_ONLY'
    case 'LIMIT' if limit_flags == 'LONG_TERM':
      return 'GOOD_TIL_TIME'
    case 'LIMIT' if limit_flags == 'SHORT_TERM':
      return 'IMMEDIATE_OR_CANCEL'
    case 'MARKET':
      return 'IMMEDIATE_OR_CANCEL'
    case other:
      raise ValidationError(f'Unknown order type "{other}" with limit flags "{limit_flags}"')

def export_order(
  order: _Place.Order, *, limit_flags: Flags = 'LONG_TERM', reduce_only: bool = False
) -> Order:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return Order(
    side=side,
    price=order_price(order),
    size=abs(signed_qty),
    flags=limit_flags if order['type'] in ('LIMIT', 'POST_ONLY') else 'SHORT_TERM',
    time_in_force=time_in_force(order, limit_flags),
    reduce_only=reduce_only,
  )
    
@dataclass
class Place(TradingMixin, _Place):
  @wrap_exceptions
  async def order(self, order: _Place.Order) -> _Place.Result:
    dydx_order = export_order(order, **(self.settings or {}))
    r = await self.private_node.place_order(self.perpetual_market, dydx_order, subaccount=self.subaccount)
    id = serialize_id(r['order'].order_id)
    return _Place.Result(id=id, details=r)