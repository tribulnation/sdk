from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trading.query_order import QueryOrder as _QueryOrder, OrderState
from tribulnation.sdk.core import ValidationError

from mexc.spot.user_data.query_order import QueryOrder as Client
from mexc.core import timestamp, OrderStatus
from mexc_sdk.core import MarketMixin, wrap_exceptions

def parse_status(status: OrderStatus) -> bool:
  match status:
    case 'NEW' | 'PARTIALLY_FILLED':
      return True
    case 'FILLED' | 'CANCELED' | 'PARTIALLY_CANCELED':
      return False
    case _:
      raise ValidationError(f'Unknown order status: {status}')

# DON'T TOUCH! Used by other modules.
async def query_order(client: Client, instrument: str, /, *, id: str) -> OrderState:
  r = await client.query_order(instrument, orderId=id)
  sign = 1 if r['side'] == 'BUY' else -1
  return OrderState(
    id=r['orderId'],
    price=Decimal(r['price']),
    qty=Decimal(r['origQty']) * sign,
    filled_qty=Decimal(r['executedQty']) * sign,
    time=timestamp.parse(r['time']),
    active=parse_status(r['status'])
  )

@dataclass
class QueryOrder(MarketMixin, _QueryOrder):
  @wrap_exceptions
  async def query_order(self, id: str) -> OrderState:
    return await query_order(self.client.spot, self.instrument, id=id)