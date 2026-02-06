from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.market.trading.cancel_order import CancelOrder as _CancelOrder, OrderState
from tribulnation.sdk.market.trading.query_order import OrderState

from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class CancelOrder(_CancelOrder, MarketMixin):
  @wrap_exceptions
  async def cancel_order(self, id: str) -> OrderState:
    r = await self.client.spot.cancel_order(self.instrument, orderId=id)
    return OrderState(
      id=r['orderId'],
      price=Decimal(r['price']),
      qty=Decimal(r['origQty']),
      filled_qty=Decimal(r['executedQty']),
      side=r['side'],
      time=datetime.now(),
      status=r['status']
    )
