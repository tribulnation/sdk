from dataclasses import dataclass

from trading_sdk.market.trade import Cancel as _Cancel
from mexc_sdk.core import SpotMixin, wrap_exceptions

@dataclass(frozen=True)
class Cancel(SpotMixin, _Cancel):
  @wrap_exceptions
  async def order(self, id: str) -> _Cancel.Result:
    r = await self.client.spot.cancel_order(self.instrument, orderId=id)
    return _Cancel.Result(details=r)

  @wrap_exceptions
  async def open(self):
    return await self.client.spot.cancel_all_orders(self.instrument)