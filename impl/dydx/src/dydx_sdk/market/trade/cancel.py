from typing_extensions import Sequence, Any
from dataclasses import dataclass

from trading_sdk.market.trade import Cancel as _Cancel
from dydx_v4_client import OrderFlags
from dydx_v4_client.node.builder import TxOptions
from dydx_sdk.core import MarketMixin, wrap_exceptions
from dydx_sdk.market.user.orders import parse_id, list_orders

@dataclass(frozen=True)
class Cancel(MarketMixin, _Cancel):
  @wrap_exceptions
  async def order(self, id: str) -> _Cancel.Result:
    order_id = parse_id(id)
    r = await self.private_node.cancel_order(order_id)
    return _Cancel.Result(details=r)


  @wrap_exceptions
  async def orders(self, ids: Sequence[str]) -> Any:
    order_ids = [parse_id(id) for id in ids]
    short_term = [o for o in order_ids if o.order_flags == OrderFlags.SHORT_TERM]
    long_term = [o for o in order_ids if o.order_flags == OrderFlags.LONG_TERM]

    results = {}
    if short_term:
      results['short_term'] = await self.private_node.batch_cancel_orders(short_term)
    if long_term:
      results['long_term'] = []
      # handle sequences serially to avoid nonce issues
      tx_options: TxOptions | None = None
      for id in long_term:
        results['long_term'].append(await self.private_node.cancel_order(id, tx_options=tx_options))
        if tx_options is None:
          tx_options = TxOptions(
            sequence=self.private_node.wallet.sequence,
            account_number=self.private_node.wallet.account_number,
            authenticators=[],
          )
        tx_options.sequence += 1
    return results


  @wrap_exceptions
  async def open(self) -> Any:
    orders = await list_orders(self, status='OPEN')
    return await self.orders([o.id for o in orders])