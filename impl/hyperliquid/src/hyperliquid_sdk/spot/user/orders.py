from typing_extensions import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk import ApiError
from trading_sdk.market.user import Orders as _Orders
from hyperliquid.info.methods.order_status import Order
from hyperliquid.info.methods.open_orders import OpenOrder
from hyperliquid_sdk.spot.core import SpotMixin

def parse_order(o: Order | OpenOrder, *, active: bool, details) -> _Orders.Order:
  qty = Decimal(o['origSz'])
  return _Orders.Order(
    id=str(o['oid']),
    price=Decimal(o['limitPx']),
    qty=qty,
    filled_qty=qty - Decimal(o['sz']),
    active=active,
    details=details,
  )

@dataclass(frozen=True)
class Orders(SpotMixin, _Orders):
  async def query(self, id: str) -> _Orders.Order:
    status = await self.client.info.order_status(self.address, int(id))
    if status['status'] == 'unknownOid':
      raise ApiError('Unknown order id')
    o = status['order']['order']
    return parse_order(o, active=status['order']['status'] == 'open', details=status['order'])
    
  async def open(self) -> Sequence[_Orders.Order]:
    orders = await self.client.info.open_orders(self.address)
    return [parse_order(o, active=True, details=o) for o in orders if o['coin'] == self.asset_name]
