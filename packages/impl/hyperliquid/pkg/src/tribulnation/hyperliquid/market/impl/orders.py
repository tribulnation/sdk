from typing_extensions import Any, Sequence
from decimal import Decimal

from tribulnation.sdk.core import ApiError
from tribulnation.sdk.market import (
  Order,
  OrderResponse,
  OrderState,
  Settings as MarketSettings,
)

from typed_hyperliquid.exchange.cancel import CancelRequestItem
from typed_hyperliquid.exchange.order import HyperliquidOrder
from typed_hyperliquid.info.order_status import OrderFound, OrderNotFound

from tribulnation.hyperliquid.core import Settings, round_price, wrap_exceptions
from .mixin import SpotMarketMixin, PerpMarketMixin


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
  price = round_price(Decimal(o['price']))
  return {
    'a': self.asset_id,
    'b': qty >= 0,
    'p': price,
    's': abs(qty),
    'r': settings.get('reduce_only', False),
    't': {'limit': {'tif': tif}},
  }


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
  s: Settings = settings.get('hyperliquid', {})
  wire = _export_order(self, order, s)
  result = await self.client.exchange.order(orders=[wire], grouping='na')
  response = result['response']
  # `status` and `response` are declared independently, so only the payload's own
  # shape tells a rejection apart from a result.
  if isinstance(response, str):
    raise ApiError(response)

  statuses = response['data']['statuses']
  if not statuses:
    raise ApiError({'error': 'empty status list', 'details': result})

  stat = statuses[0]
  if 'error' in stat:
    raise ApiError(stat['error'])
  if 'resting' in stat:
    return OrderResponse(id=str(stat['resting']['oid']), details=stat)
  return OrderResponse(id=str(stat['filled']['oid']), details=stat)


@wrap_exceptions
async def cancel_order(
  self: SpotMarketMixin | PerpMarketMixin, id: str, *, settings: MarketSettings = {}
) -> Any:
  cancel: CancelRequestItem = {'a': self.asset_id, 'o': int(id)}
  result = await self.client.exchange.cancel(cancels=[cancel])
  response = result['response']
  if isinstance(response, str):
    raise ApiError(response)
  statuses = response['data']['statuses']
  if not statuses:
    raise ApiError({'error': 'empty status list', 'details': result})
  s = statuses[0]
  if s == 'success':
    return s
  raise ApiError(s['error'])


@wrap_exceptions
async def query_order(
  self: SpotMarketMixin | PerpMarketMixin, id: str
) -> OrderState | None:
  status: OrderFound | OrderNotFound = await self.client.info.order_status(
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
