from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trading.open_orders import OpenOrders as _OpenOrders, OrderState

from mexc.core import timestamp
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class OpenOrders(_OpenOrders, MarketMixin):
  @wrap_exceptions
  async def open_orders(self) -> list[OrderState]:
    orders = await self.client.spot.open_orders(self.instrument)
    return [
      OrderState(
        id=o['orderId'],
        price=Decimal(o['price']),
        qty=Decimal(o['origQty']),
        filled_qty=Decimal(o['executedQty']),
        time=timestamp.parse(o['time']),
        side=o['side'],
        status=o['status']
      )
      for o in orders
    ]
