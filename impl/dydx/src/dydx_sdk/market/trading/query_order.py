from dataclasses import dataclass
from decimal import Decimal

from v4_proto.dydxprotocol.clob.order_pb2 import OrderId

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market.types.order import OrderState, OrderStatus as _OrderStatus
from tribulnation.sdk.market.trading.query_order import QueryOrder as _QueryOrder

from dydx.core import timestamp as ts
from dydx.core.types import OrderStatus
from dydx.indexer.data import IndexerData
from dydx_sdk.core import MarketMixin, UserDataMixin, wrap_exceptions

def parse_status(status: OrderStatus) -> _OrderStatus:
  match status:
    case 'OPEN' | 'PENDING':
      return 'NEW'
    case 'CANCELED':
      return 'CANCELED'
    case 'FILLED':
      return 'FILLED'
    case 'UNTRIGGERED':
      return 'UNTRIGGERED'
    case _:
      raise ValueError(f'Unknown order status: {status}')

async def query_order(indexer_data: IndexerData, *, address: str, instrument: str, id: str) -> OrderState:
  order_id = OrderId.FromString(id.encode())
  client_id = str(order_id.client_id)
  orders = await indexer_data.list_orders(address, ticker=instrument, unsafe=True)
  for o in orders:
    if o['clientId'] == client_id:
      return OrderState(
        id=id,
        price=Decimal(o['price']),
        qty=Decimal(o['size']),
        filled_qty=Decimal(o['totalFilled']),
        side=o['side'],
        time=ts.parse(o['updatedAt']),
        status=parse_status(o['status'])
      )
  
  raise ApiError(f'Order not found: {id}')

@dataclass
class QueryOrder(MarketMixin, UserDataMixin, _QueryOrder):

  @wrap_exceptions
  async def query_order(self, id: str) -> OrderState:
    return await query_order(self.indexer_data, address=self.address, instrument=self.market, id=id)