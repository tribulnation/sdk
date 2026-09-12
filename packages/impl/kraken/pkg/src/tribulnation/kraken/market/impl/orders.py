"""Open orders, over the account-wide `OpenOrders`."""

from typing_extensions import TYPE_CHECKING, Sequence
from decimal import Decimal

from tribulnation.sdk.market import OrderState

from typed_kraken.spot.account.open_orders import OpenOrder

if TYPE_CHECKING:
  from .mixin import MarketMixin


def parse_order(txid: str, order: OpenOrder) -> OrderState:
  """Map one open order onto an `OrderState`.

  `pending` is an order awaiting book entry: not yet resting, but not finished
  with either, so it counts as active alongside `open`.
  """
  descr = order.get('descr') or {}
  sign = 1 if descr.get('type') == 'buy' else -1
  return OrderState(
    id=txid,
    price=descr.get('price', Decimal(0)),
    qty=sign * order.get('vol', Decimal(0)),
    filled_qty=sign * order.get('vol_exec', Decimal(0)),
    active=order.get('status') in ('pending', 'open'),
    details=order,
  )


async def open_orders(self: 'MarketMixin') -> Sequence[OrderState]:
  """Fetch the market's currently open orders.

  `OpenOrders` is account-wide and unpaged, so the answer is filtered here on the
  order description's pair, which Kraken spells as the altname.
  """
  raw = await self.call_kraken(self.client.spot.account.open_orders)
  return [
    parse_order(txid, order)
    for txid, order in (raw.get('open') or {}).items()
    if (order.get('descr') or {}).get('pair') == self.altname
  ]
