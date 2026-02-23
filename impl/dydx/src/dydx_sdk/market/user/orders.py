from dataclasses import dataclass
from decimal import Decimal
import base64

from trading_sdk.market.user import Orders as _Orders
from trading_sdk.core import ApiError, ValidationError

from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId
from v4_proto.dydxprotocol.clob.order_pb2 import OrderId

from dydx.indexer.types import OrderStatus, OrderState
from dydx_sdk.core import MarketMixin, wrap_exceptions

def parse_status(status: OrderStatus) -> bool:
  match status:
    case 'OPEN' | 'PENDING' | 'UNTRIGGERED' | 'BEST_EFFORT_OPENED':
      return True
    case 'CANCELED' | 'FILLED' | 'BEST_EFFORT_CANCELED':
      return False
    case _:
      raise ValidationError(f'Unknown order status: {status}')

def order_id(o: OrderState, *, address: str) -> OrderId:
  return OrderId(
    client_id=int(o['clientId']),
    order_flags=int(o['orderFlags']),
    clob_pair_id=int(o['clobPairId']),
    subaccount_id=SubaccountId(
      owner=address,
      number=int(o['subaccountNumber'])
    )
  )

def serialize_id(id: OrderId) -> str:
  return base64.b64encode(id.SerializeToString()).decode()

def parse_id(id: str) -> OrderId:
  return OrderId.FromString(base64.b64decode(id))

def parse_state(o: OrderState, *, address: str) -> _Orders.Order:
  active = parse_status(o['status'])
  sign = 1 if Decimal(o['size']) > 0 else -1
  return _Orders.Order(
    id=serialize_id(order_id(o, address=address)),
    price=Decimal(o['price']),
    qty=Decimal(o['size']) * sign,
    filled_qty=Decimal(o['totalFilled']) * sign,
    active=active,
    details=o,
  )

@wrap_exceptions
async def list_orders(self: MarketMixin, *, status: OrderStatus | None = None) -> list[_Orders.Order]:
  orders = await self.indexer.data.list_orders(
    self.address, subaccount=self.subaccount,
    ticker=self.market, status=status,
  )
  return [parse_state(o, address=self.address) for o in orders]

@dataclass(frozen=True)
class Orders(MarketMixin, _Orders):
  async def query(self, id: str) -> _Orders.Order:
    orders = await list_orders(self)
    for o in orders:
      if o.id == id:
        return o
    raise ApiError(f'Order not found: {id}')

  async def open(self):
    return await list_orders(self, status='OPEN')