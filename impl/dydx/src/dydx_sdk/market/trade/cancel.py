from dataclasses import dataclass

from tribulnation.sdk.market.trade import Cancel as _Cancel

from dydx_v4_client import OrderFlags
from dydx_sdk.core import PrivateNodeMixin, wrap_exceptions

from dydx_sdk.market.user.orders import parse_id

@dataclass
class Cancel(PrivateNodeMixin, _Cancel):
  @wrap_exceptions
  async def order(self, id: str) -> _Cancel.Result:
    order_id = parse_id(id)
    if order_id.order_flags == OrderFlags.LONG_TERM:
      r = await self.private_node.cancel_order(order_id)
      return _Cancel.Result(details=r)
    else:
      # else it's a short term order, which gets automatically canceled
      return _Cancel.Result(details='Did nothing: short term orders get automatically canceled.')