from dataclasses import dataclass
from decimal import Decimal

from sdk.core import Num, fmt_num

from mexc.spot.trading.place_order import LimitOrder
from mexc_sdk.core import MarketMixin, wrap_exceptions

@dataclass
class EditOrder(MarketMixin):
  @wrap_exceptions
  async def edit_order(self, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    state = await self.client.spot.cancel_order(self.instrument, orderId=id)

    if price is None:
      price = state['price']

    if qty is None:
      qty = Decimal(state['origQty']) - Decimal(state['executedQty'])

    r = await self.client.spot.place_order(self.instrument, LimitOrder(
      type='LIMIT',
      side=state['side'],
      price=fmt_num(price),
      quantity=fmt_num(qty)
    ))
    return r['orderId']
