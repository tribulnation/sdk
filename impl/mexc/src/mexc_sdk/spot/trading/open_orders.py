from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.market.trading.open_orders import OpenOrders as _OpenOrders, OrderState

from mexc.core import timestamp
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class OpenOrders(MarketMixin, _OpenOrders):
  @wrap_exceptions
  async def open_orders(self) -> list[OrderState]:
    orders = await self.client.spot.open_orders(self.instrument)
    out: list[OrderState] = []
    for o in orders:
      sign = 1 if o['side'] == 'BUY' else -1
      out.append(OrderState(
        id=o['orderId'],
        price=Decimal(o['price']),
        qty=Decimal(o['origQty']) * sign,
        filled_qty=Decimal(o['executedQty']) * sign,
        time=timestamp.parse(o['time']),
        status=o['status']
      ))
    return out
