from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.market.trading.cancel_order import CancelOrder as _CancelOrder, OrderState
from tribulnation.sdk.market.trading.query_order import OrderState

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class CancelOrder(MarketMixin, _CancelOrder):
  @wrap_exceptions
  async def cancel_order(self, id: str) -> OrderState:
    r = await self.client.spot.cancel_order(self.instrument, orderId=id)
    sign = 1 if r['side'] == 'BUY' else -1
    return OrderState(
      id=r['orderId'],
      price=Decimal(r['price']),
      qty=Decimal(r['origQty']) * sign,
      filled_qty=Decimal(r['executedQty']) * sign,
      time=datetime.now(),
      status=r['status']
    )
