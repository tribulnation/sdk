from dataclasses import dataclass

from v4_proto.dydxprotocol.clob.order_pb2 import OrderId
from dydx_v4_client import OrderFlags

from tribulnation.sdk.market.trading.cancel_order import CancelOrder as _CancelOrder
from tribulnation.sdk.market.trading.query_order import OrderState

from dydx_sdk.core import MarketMixin, TradingMixin, wrap_exceptions
from .query_order import query_order

@dataclass
class CancelOrder(MarketMixin, TradingMixin, _CancelOrder):
  @wrap_exceptions
  async def cancel_order(self, instrument: str, /, *, id: str) -> OrderState:
    order_id = OrderId.FromString(id) # type: ignore
    if order_id.order_flags == OrderFlags.LONG_TERM:
      await self.node.cancel_order(order_id, unsafe=True)
    # else it's a short term order, which gets automatically canceled
    return await query_order(self.indexer_data, address=self.node.address, instrument=self.market, id=id)