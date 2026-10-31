from typing_extensions import Any, Sequence
from decimal import Decimal
import asyncio

from tribulnation.sdk.core import ApiError, OrderNotFound, OrderRejected
from tribulnation.sdk.market.types.rules import valid_price
from tribulnation.sdk.market import (
  Order,
  OrderResponse,
  OrderState,
  Settings as MarketSettings,
)

from typed_hyperliquid.exchange.cancel import CancelRequestItem
from typed_hyperliquid.exchange.modify_orders import (
  FilledOrderStatus,
  OrderModification,
  OrderStatusError,
  RestingOrderStatus,
)
from typed_hyperliquid.exchange.order import HyperliquidOrder
from typed_hyperliquid.info import order_status

from tribulnation.hyperliquid.core import (
  Settings,
  MAX_SIGNIFICANT_FIGURES,
  plain_decimal,
  wrap_exceptions,
)
from .mixin import SpotMarketMixin, PerpMarketMixin


GONE = ('never placed', 'canceled or filled')
"""Parts of Hyperliquid's errors for an order that no longer rests: the cancel's `Order was
never placed, already canceled, or filled.` and the modify's `Cannot modify canceled or
filled order` (testnet, 2026-10-31)."""
NEW_ORDER_REFUSED = 'Error placing new order during modify:'
"""Prefix of a modify's error when the old order was cancelled and the new one refused
(e.g. a post-only order that would cross, or one below the minimum value): nothing
rests (testnet, 2026-10-31)."""


def gone(error: str) -> bool:
  """Whether `error` says the order no longer rests."""
  return any(part in error for part in GONE)


def _active(status: str) -> bool:
  # conservative: only 'open' is definitely active; 'triggered' is still live too
  return status in {'open', 'triggered', 'scheduledCancel'}


def _export_order(
  self: SpotMarketMixin | PerpMarketMixin,
  o: Order,
  settings: Settings,
) -> HyperliquidOrder:
  if o['type'] == 'LIMIT':
    tif = settings.get('limit_tif', 'Gtc')
  elif o['type'] == 'MARKET':
    tif = 'Ioc'
  elif o['type'] == 'POST_ONLY':
    tif = 'Alo'
  else:
    raise ValueError(f'Unknown order type: {o["type"]}')

  qty = Decimal(o['qty'])
  price = Decimal(o['price'])
  if not valid_price(price, tick_size=self.tick_size, sig_figs=MAX_SIGNIFICANT_FIGURES):
    raise ValueError(
      f'Price {price} is off the Hyperliquid grid (at most {MAX_SIGNIFICANT_FIGURES} '
      'significant figures and the tick size, or an integer): round it with Rules'
    )
  wire: HyperliquidOrder = {
    'a': self.asset_id,
    'b': qty >= 0,
    'p': plain_decimal(price),
    's': plain_decimal(abs(qty)),
    'r': settings.get('reduce_only', False),
    't': {'limit': {'tif': tif}},
  }
  if (client_order_id := o.get('client_order_id')) is not None:
    # Sent as-is: the venue rejects anything but a 128-bit hex string (`0x` + 32 hex).
    wire['c'] = client_order_id
  return wire


@wrap_exceptions
async def open_orders(self: SpotMarketMixin | PerpMarketMixin) -> Sequence[OrderState]:
  dex = getattr(self, 'dex_name', None)
  if dex is not None:
    orders = await self.client.info.frontend_open_orders(user=self.address, dex=dex)
  else:
    orders = await self.client.info.frontend_open_orders(user=self.address)

  out: list[OrderState] = []
  for o in orders:
    if o.get('coin') != self.asset_name:
      continue
    qty = Decimal(o['origSz'])
    out.append(
      OrderState(
        id=str(o['oid']),
        price=Decimal(o['limitPx']),
        qty=qty,
        filled_qty=qty - Decimal(o['sz']),
        active=True,
        details=o,
      )
    )
  return out


@wrap_exceptions
async def place_order(
  self: SpotMarketMixin | PerpMarketMixin,
  order: Order,
  *,
  settings: MarketSettings = {},
) -> OrderResponse:
  """
  Place one order and map Hyperliquid's answer to the SDK contract.

  `filled_qty` is the `filled` status's `totalSz`. A `resting` status reports no fill
  size, and a GTC order that partly crosses on arrival also answers `resting`, so its
  `filled_qty` is `None`.

  Raises:
    ValueError: The price is off the venue's grid (`Rules.valid_price`); round it with
      the market's `Rules`.
    OrderRejected: The action was refused as a whole (`status == 'err'`), or the
      order's own status carries an `error` (e.g. an IOC that could not match).
    ApiError: The response carried no order status, so the outcome is unknown.
  """
  s: Settings = settings.get('hyperliquid', {})
  wire = _export_order(self, order, s)
  result = await self.client.exchange.order(orders=[wire], grouping='na')
  if result['status'] == 'err':
    raise OrderRejected(result['response'])

  statuses = result['response']['data']['statuses']
  if not statuses:
    raise ApiError({'error': 'empty status list', 'details': result})

  stat = statuses[0]
  if 'error' in stat:
    raise OrderRejected(stat['error'])
  return placed(stat)


def placed(stat: RestingOrderStatus | FilledOrderStatus) -> OrderResponse:
  """The response for an order resting or filled on placement."""
  if 'resting' in stat:
    return OrderResponse(id=str(stat['resting']['oid']), details=stat)
  else:
    filled = stat['filled']
    return OrderResponse(
      id=str(filled['oid']), details=stat, filled_qty=Decimal(filled['totalSz'])
    )


@wrap_exceptions
async def cancel_order(
  self: SpotMarketMixin | PerpMarketMixin, id: str, *, settings: MarketSettings = {}
) -> Any:
  cancel: CancelRequestItem = {'a': self.asset_id, 'o': int(id)}
  result = await self.client.exchange.cancel(cancels=[cancel])
  if result['status'] == 'err':
    raise ApiError(result['response'])
  statuses = result['response']['data']['statuses']
  if not statuses:
    raise ApiError({'error': 'empty status list', 'details': result})
  s = statuses[0]
  if s == 'success':
    return s
  elif gone(s['error']):
    raise OrderNotFound(s['error'])
  else:
    raise ApiError(s['error'])


async def replace_orders(
  self: SpotMarketMixin | PerpMarketMixin,
  orders: Sequence[tuple[str, Order]],
  *,
  settings: MarketSettings = {},
) -> Sequence[OrderResponse | Exception]:
  """
  Replace POST_ONLY entries in one `batchModify`, the rest by cancel then place.

  Without the always-place flag, Hyperliquid modifies only into `Alo` orders, and places
  nothing when the old order's cancel fails; the flag would also place after a cancel
  failing for another reason. Each modified order gets a new ID. An entry whose old
  order is gone is placed afresh. An entry whose new order was refused after the old one
  was cancelled (`NEW_ORDER_REFUSED`) is an `OrderRejected`; any other entry error is an
  `ApiError`, since the old order may still rest. A refused or failed action fails each
  of its entries.
  """
  s: Settings = settings.get('hyperliquid', {})
  modified = [i for i, (_, order) in enumerate(orders) if order['type'] == 'POST_ONLY']
  others = [i for i in range(len(orders)) if i not in modified]

  async def place(order: Order) -> OrderResponse | Exception:
    """Place an entry whose old order is gone."""
    try:
      return await place_order(self, order, settings=settings)
    except Exception as e:
      return e

  async def cancel_then_place(id: str, order: Order) -> OrderResponse | Exception:
    """Replace an entry `batchModify` can't take, as the SDK default does."""
    try:
      await cancel_order(self, id)
    except OrderNotFound:
      pass
    except Exception as e:
      return e
    return await place(order)

  async def modify() -> Sequence[OrderResponse | Exception]:
    """The modified entries' outcomes, in their order."""
    if not modified:
      return []
    modifies: list[OrderModification] = [
      {'oid': int(orders[i][0]), 'order': _export_order(self, orders[i][1], s)}
      for i in modified
    ]

    @wrap_exceptions
    async def send():
      """Send the action, its errors translated."""
      return await self.client.exchange.modify_orders(modifies)

    try:
      result = await send()
    except Exception as e:
      return [e] * len(modified)
    if result['status'] == 'err':
      return [ApiError(result['response'])] * len(modified)
    statuses = result['response']['data']['statuses']
    if len(statuses) != len(modified):
      return [ApiError({'error': 'a status per modify', 'details': result})] * len(
        modified
      )

    async def outcome(
      stat: RestingOrderStatus | FilledOrderStatus | OrderStatusError, order: Order
    ) -> OrderResponse | Exception:
      """The entry's response, placing it afresh when its old order was gone."""
      if 'error' not in stat:
        return placed(stat)
      elif gone(stat['error']):
        return await place(order)
      elif stat['error'].startswith(NEW_ORDER_REFUSED):
        return OrderRejected(stat['error'])
      else:
        return ApiError(stat['error'])

    return await asyncio.gather(
      *[outcome(stat, orders[i][1]) for stat, i in zip(statuses, modified)]
    )

  done, rest = await asyncio.gather(
    modify(), asyncio.gather(*[cancel_then_place(*orders[i]) for i in others])
  )
  by_index = dict(zip(modified, done)) | dict(zip(others, rest))
  return [by_index[i] for i in range(len(orders))]


async def replace_order(
  self: SpotMarketMixin | PerpMarketMixin,
  id: str,
  order: Order,
  *,
  settings: MarketSettings = {},
) -> OrderResponse:
  """Replace one order through `replace_orders`, raising its error."""
  (result,) = await replace_orders(self, [(id, order)], settings=settings)
  if isinstance(result, Exception):
    raise result
  return result


@wrap_exceptions
async def query_order(
  self: SpotMarketMixin | PerpMarketMixin, id: str
) -> OrderState | None:
  status: (
    order_status.OrderFound | order_status.OrderNotFound
  ) = await self.client.info.order_status(
    user=self.address,
    oid=int(id),
  )
  if status['status'] == 'unknownOid':
    return None

  entry = status['order']
  o = entry['order']
  if o.get('coin') != self.asset_name:
    return None

  qty = Decimal(o['origSz'])
  return OrderState(
    id=str(o['oid']),
    price=Decimal(o['limitPx']),
    qty=qty,
    filled_qty=qty - Decimal(o['sz']),
    active=_active(entry['status']),
    details=status,
  )
