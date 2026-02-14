from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market_v2.user import Orders as _Orders
from tribulnation.sdk.core import ApiError, ValidationError

from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId
from v4_proto.dydxprotocol.clob.order_pb2 import OrderId

from dydx.core import timestamp as ts
from dydx.indexer.types import OrderStatus, OrderState
from dydx_sdk.core import MarketMixin, IndexerDataMixin, SubaccountMixin, wrap_exceptions

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
  return id.SerializeToString().hex()

def parse_id(id: str) -> OrderId:
  return OrderId.FromString(bytes.fromhex(id))

def parse_state(o: OrderState, *, address: str) -> _Orders.Order:
  active = parse_status(o['status'])
  sign = 1 if Decimal(o['size']) > 0 else -1
  return _Orders.Order(
    id=serialize_id(order_id(o, address=address)),
    price=Decimal(o['price']),
    qty=Decimal(o['size']) * sign,
    filled_qty=Decimal(o['totalFilled']) * sign,
    active=active,
    time=ts.parse(o.get('updatedAt') or '1970-01-01T00:00:00Z'),
    details=o,
  )

@dataclass
class Orders(MarketMixin, IndexerDataMixin, SubaccountMixin, _Orders):
  
  @wrap_exceptions
  async def _list_orders(self) -> list[_Orders.Order]:
    orders = await self.indexer_data.list_orders(
      self.address, ticker=self.market, subaccount=self.subaccount,
    )
    return [parse_state(o, address=self.address) for o in orders]

  async def query(self, id: str) -> _Orders.Order:
    orders = await self._list_orders()
    for o in orders:
      if o.id == id:
        return o
    raise ApiError(f'Order not found: {id}')

  async def open(self):
    orders = await self._list_orders()
    return [o for o in orders if o.active]