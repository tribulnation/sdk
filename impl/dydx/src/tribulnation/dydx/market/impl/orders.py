from typing_extensions import Literal, Sequence
from decimal import Decimal
import base64

from dydx.indexer.data.list_parent_orders import Order as IndexerOrder
from dydx.node.orders import OrderParams, OrderPlacement, TimeInForce, Flags
from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings as MarketSettings
from dydx.protos.dydxprotocol import clob, subaccounts
from tribulnation.dydx.core import wrap_exceptions
from .mixin import MarketMixin, Settings

def _active(status: str) -> bool:
  match status:
    case 'OPEN' | 'PENDING' | 'UNTRIGGERED' | 'BEST_EFFORT_OPENED':
      return True
    case 'CANCELED' | 'FILLED' | 'BEST_EFFORT_CANCELED':
      return False
    case _:
      raise ValidationError(f'Unknown order status: {status}')


def _sign(side: str | None) -> int:
  if side == 'BUY':
    return 1
  if side == 'SELL':
    return -1
  raise ValidationError(f'Unknown order side: {side}')


def _protobuf_id(order: IndexerOrder, *, address: str) -> clob.OrderId:
  """Build a protocol order ID for an indexer order."""
  return clob.OrderId(
    client_id=int(order['clientId']),
    order_flags=int(order['orderFlags']),
    clob_pair_id=int(order['clobPairId']),
    subaccount_id=subaccounts.SubaccountId(
      owner=address,
      number=int(order['subaccountNumber']),
    ),
  )

def serialize_id(order_id: clob.OrderId) -> str:
  """Serialize a dYdX protocol order ID for the SDK order API."""
  return base64.b64encode(bytes(order_id)).decode()


def parse_id(id: str) -> clob.OrderId:
  """Parse an SDK order ID into a dYdX protocol order ID."""
  return clob.OrderId.FromString(base64.b64decode(id))

def parse_state(order: IndexerOrder, *, address: str) -> OrderState:
  sign = _sign(order['side'])
  return OrderState(
    id=serialize_id(_protobuf_id(order, address=address)),
    price=Decimal(order['price']),
    qty=Decimal(order['size']) * sign,
    filled_qty=Decimal(order['totalFilled']) * sign,
    active=_active(order['status']),
    details=order,
  )

@wrap_exceptions
async def list_orders(
  self: MarketMixin, *,
  status: Literal['OPEN', 'FILLED', 'CANCELED', 'BEST_EFFORT_CANCELED', 'UNTRIGGERED', 'BEST_EFFORT_OPENED', 'PENDING'] | None = None,
) -> list[OrderState]:
  address = self.address
  orders = await self.indexer.data.list_parent_orders(
    address=address,
    parent_subaccount=self.shared.parent_subaccount,
    ticker=self.market,
    status=status,
  )
  # Scope to the addressed subaccount. The parent exchange (subaccount == parent) keeps
  # the parent-aggregate view; a child exchange filters down to just that child.
  if self.subaccount != self.shared.parent_subaccount:
    orders = [order for order in orders if order['subaccountNumber'] == self.subaccount]
  return [parse_state(order, address=address) for order in orders]

def _time_in_force(order: Order, settings: Settings) -> TimeInForce:
  if order['type'] == 'POST_ONLY':
    return 'POST_ONLY'
  if order['type'] == 'MARKET':
    return settings.get('market_tif', 'IMMEDIATE_OR_CANCEL')
  return settings.get('limit_tif', 'GOOD_TIL_TIME')

def _flags(order: Order, settings: Settings) -> Flags:
  if order['type'] == 'MARKET':
    return settings.get('market_flags', 'SHORT_TERM')
  else:
    return settings.get('limit_flags', 'LONG_TERM')


def export_order(order: Order, settings: Settings) -> OrderParams:
  """Convert an SDK order into dYdX ergonomic order parameters."""
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return {
    'side': side,
    'price': Decimal(order['price']),
    'size': abs(signed_qty),
    'flags': _flags(order, settings),
    'time_in_force': _time_in_force(order, settings),
    'reduce_only': settings.get('reduce_only', False),
  }

async def with_expiry(self: MarketMixin, params: OrderParams, settings: Settings) -> OrderParams:
  """Apply SDK-configured dYdX order expiry deltas."""
  if params['flags'] == 'SHORT_TERM' and (delta := settings.get('short_term_gtb')) is not None:
    latest = await self.client.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None:
      raise ValidationError('Latest dYdX block response did not include a header')
    return {**params, 'good_til_block': block.header.height + delta}
  if params['flags'] in {'LONG_TERM', 'CONDITIONAL'} and (delta := settings.get('long_term_gtbt')) is not None:
    latest = await self.client.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None or block.header.time is None:
      raise ValidationError('Latest dYdX block response did not include a timestamp')
    return {**params, 'good_til_block_time': int(block.header.time.timestamp()) + delta}
  return params

@wrap_exceptions
async def place_order(self: MarketMixin, order: Order, *, settings: MarketSettings = {}) -> OrderResponse:
  s: Settings = settings.get('dydx', {})
  response = await self.client.node.place_order(
    self.perpetual_market,
    order=await with_expiry(self, export_order(order, s), s),
    subaccount=self.subaccount,
  )
  order_id = response.order.order_id
  if order_id is None:
    raise ValidationError('dYdX place order response did not include an order ID')
  return OrderResponse(
    id=serialize_id(order_id),
    details=response,
  )

@wrap_exceptions
async def cancel_order(self: MarketMixin, id: str, *, settings: MarketSettings = {}):
  return await self.client.node.cancel_order(parse_id(id))

@wrap_exceptions
async def cancel_orders(self: MarketMixin, ids: Sequence[str], *, settings: MarketSettings = {}):
  order_ids = [parse_id(id) for id in ids]
  short_term = [order_id for order_id in order_ids if order_id.order_flags == 0]
  long_term = [order_id for order_id in order_ids if order_id.order_flags != 0]

  results: dict = {}
  if short_term:
    results['short_term'] = await self.client.node.batch_cancel_orders(short_term)
  if long_term:
    results['long_term'] = []
    for order_id in long_term:
      results['long_term'].append(await self.client.node.cancel_order(order_id))

  return results

@wrap_exceptions
async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  for order in await list_orders(self):
    if order.id == id:
      return order

@wrap_exceptions
async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  return await list_orders(self, status='OPEN')
