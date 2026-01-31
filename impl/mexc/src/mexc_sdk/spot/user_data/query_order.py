from dataclasses import dataclass
from decimal import Decimal

from sdk.market.trading.query_order import QueryOrder as _QueryOrder, OrderState

from mexc.spot.user_data.query_order import QueryOrder as Client
from mexc.core import timestamp
from mexc_sdk.core import MarketMixin, wrap_exceptions

# DON'T TOUCH! Used by other modules.
async def query_order(client: Client, instrument: str, /, *, id: str) -> OrderState:
  r = await client.query_order(instrument, orderId=id)
  return OrderState(
    id=r['orderId'],
    price=Decimal(r['price']),
    qty=Decimal(r['origQty']),
    filled_qty=Decimal(r['executedQty']),
    time=timestamp.parse(r['time']),
    side=r['side'],
    status=r['status']
  )

@dataclass
class QueryOrder(_QueryOrder, MarketMixin):
  @wrap_exceptions
  async def query_order(self, id: str) -> OrderState:
    return await query_order(self.client.spot, self.instrument, id=id)