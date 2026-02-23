from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.core import ValidationError
from trading_sdk.market.user import Orders as _Orders

from mexc.core import OrderStatus
from mexc.spot.user_data.query_order import OrderState
from mexc_sdk.core import SpotMixin, wrap_exceptions

def parse_status(status: OrderStatus) -> bool:
  match status:
    case 'NEW' | 'PARTIALLY_FILLED':
      return True
    case 'FILLED' | 'CANCELED' | 'PARTIALLY_CANCELED':
      return False
    case _:
      raise ValidationError(f'Unknown order status: {status}')

def parse_order(order: OrderState) -> _Orders.Order:
  sign = 1 if order['side'] == 'BUY' else -1
  return _Orders.Order(
    id=order['orderId'],
    price=Decimal(order['price']),
    qty=Decimal(order['origQty']) * sign,
    filled_qty=Decimal(order['executedQty']) * sign,
    active=parse_status(order['status']),
    details=order,
  )

@dataclass(frozen=True)
class Orders(SpotMixin, _Orders):
  @wrap_exceptions
  async def query(self, id: str) -> _Orders.Order:
    order = await self.client.spot.query_order(self.instrument, orderId=id)
    return parse_order(order)

  @wrap_exceptions
  async def open(self):
    orders = await self.client.spot.open_orders(self.instrument)
    return [parse_order(o) for o in orders]