from decimal import Decimal

from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market.types.order import OrderState as _OrderState

from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId
from v4_proto.dydxprotocol.clob.order_pb2 import OrderId

from dydx.core import timestamp as ts
from dydx.core.types import OrderStatus, OrderState

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

def parse_state(o: OrderState, *, address: str) -> _OrderState:
  active = parse_status(o['status'])
  sign = 1 if Decimal(o['size']) > 0 else -1
  return _OrderState(
    id=serialize_id(order_id(o, address=address)),
    price=Decimal(o['price']),
    qty=Decimal(o['size']) * sign,
    filled_qty=Decimal(o['totalFilled']) * sign,
    active=active,
    time=ts.parse(o.get('updatedAt') or '1970-01-01T00:00:00Z'),
  )
