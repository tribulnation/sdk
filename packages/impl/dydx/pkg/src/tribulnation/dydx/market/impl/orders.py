from typing_extensions import Literal, Mapping, Sequence, TypedDict
from decimal import Decimal
from functools import cache
import base64
import uuid

from typed_dydx.indexer.schemas import (
  Order as IndexerOrder,
  OrderSubaccountMessage,
)
from typed_dydx.node.orders.types import (
  ConditionalOrderParams,
  Flags,
  LongTermOrderParams,
  OrderParams,
  ShortTermOrderParams,
  TimeInForce,
)
from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market import (
  Order,
  OrderResponse,
  OrderState,
  Settings as MarketSettings,
)
from typed_dydx.protos.cosmos.tx.v1beta1 import BroadcastTxResponse
from typed_dydx.protos.dydxprotocol import clob, subaccounts
from tribulnation.dydx.core import wrap_exceptions
from .mixin import MarketMixin, Settings, settings_adapter


class CancelResults(TypedDict, total=False):
  """Broadcast responses of a batch cancel, by the order flavour each went through."""

  short_term: BroadcastTxResponse
  """The single batch transaction cancelling every short-term order."""
  long_term: list[BroadcastTxResponse]
  """One transaction per long-term order, in the order given."""


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


INDEXER_NAMESPACE = uuid.UUID('0f9da948-a6fb-4c45-9edc-4685c3f3317d')
"""Namespace of the indexer's uuid5 ids (v4-chain `indexer/packages/postgres/src/helpers/uuid.ts`)."""
MAX_SUBACCOUNT = 128_000
"""The highest valid subaccount number."""


def _protobuf_id(
  order: IndexerOrder | OrderSubaccountMessage,
  *,
  address: str,
  subaccount: int | None = None,
) -> clob.OrderId:
  """Build a protocol order ID for an indexer order.

  Args:
    order: A REST order, or one pushed on a subaccounts stream.
    address: The subaccount owner.
    subaccount: The subaccount number, for an order that does not carry it.
  """
  number = order.get('subaccountNumber')
  if number is None:
    number = subaccount
  if number is None:
    raise ValidationError(f'Order {order["id"]} carries no subaccountNumber')
  flags = order.get('orderFlags')
  if flags is None:
    raise ValidationError(f'Order {order["id"]} carries no orderFlags')
  return clob.OrderId(
    client_id=int(order['clientId']),
    order_flags=int(flags),
    clob_pair_id=int(order['clobPairId']),
    subaccount_id=subaccounts.SubaccountId(owner=address, number=int(number)),
  )


def indexer_subaccount_id(address: str, number: int) -> str:
  """The indexer's id of a subaccount (`SubaccountTable.uuid`)."""
  return str(uuid.uuid5(INDEXER_NAMESPACE, f'{address}-{number}'))


def indexer_order_id(order_id: clob.OrderId) -> str:
  """The indexer's id of a protocol order (`OrderTable.uuid`)."""
  subaccount = order_id.subaccount_id
  if subaccount is None:
    raise ValidationError('dYdX order id carries no subaccount')
  return str(
    uuid.uuid5(
      INDEXER_NAMESPACE,
      f'{indexer_subaccount_id(subaccount.owner, subaccount.number)}'
      f'-{order_id.client_id}-{order_id.clob_pair_id}-{order_id.order_flags}',
    )
  )


def serialize_id(order_id: clob.OrderId) -> str:
  """Serialize a dYdX protocol order ID for the SDK order API."""
  return base64.b64encode(bytes(order_id)).decode()


@cache
def subaccount_numbers(address: str, parent: int) -> Mapping[str, int]:
  """A parent subaccount's and its children's numbers, by indexer subaccount id.

  The indexer's subaccount id is the uuid5 of `<address>-<number>`; the children of
  parent `p` are `p + 128`, `p + 256`, ...
  """
  return {
    indexer_subaccount_id(address, number): number
    for number in range(parent, MAX_SUBACCOUNT + 1, 128)
  }


def stream_order_ids(
  orders: Sequence[OrderSubaccountMessage], *, address: str, parent: int
) -> dict[str, str]:
  """SDK ids of the orders in a parent subaccounts message, by indexer order id.

  Pushed orders carry the indexer's subaccount id, not its number, which is recovered
  from the parent's subaccount ids. Orders without flags are left out.
  """
  numbers = subaccount_numbers(address, parent)
  ids: dict[str, str] = {}
  for order in orders:
    number = numbers.get(order['subaccountId'])
    if number is None or order.get('orderFlags') is None:
      continue
    ids[order['id']] = serialize_id(
      _protobuf_id(order, address=address, subaccount=number)
    )
  return ids


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
  self: MarketMixin,
  *,
  status: Literal[
    'OPEN',
    'FILLED',
    'CANCELED',
    'BEST_EFFORT_CANCELED',
    'UNTRIGGERED',
    'BEST_EFFORT_OPENED',
    'PENDING',
  ]
  | None = None,
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
    orders = [o for o in orders if o.get('subaccountNumber') == self.subaccount]
  return [parse_state(order, address=address) for order in orders]


def _default_tif(order: Order) -> TimeInForce:
  if order['type'] == 'POST_ONLY':
    return 'POST_ONLY'
  if order['type'] == 'MARKET':
    return 'IMMEDIATE_OR_CANCEL'
  else:
    return 'GOOD_TIL_TIME'


def _time_in_force(order: Order, settings: Settings) -> TimeInForce:
  return settings.get('tif', _default_tif(order))


def _default_flags(order: Order) -> Flags:
  if order['type'] == 'MARKET':
    return 'SHORT_TERM'
  else:
    return 'LONG_TERM'


def _flags(order: Order, settings: Settings) -> Flags:
  return settings.get('flags', _default_flags(order))


def export_order(order: Order, settings: Settings) -> OrderParams:
  """Convert an SDK order into dYdX ergonomic order parameters."""
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  price = Decimal(order['price'])
  size = abs(signed_qty)
  time_in_force = _time_in_force(order, settings)
  reduce_only = settings.get('reduce_only', False)
  match _flags(order, settings):
    case 'SHORT_TERM':
      return ShortTermOrderParams(
        side=side,
        price=price,
        size=size,
        time_in_force=time_in_force,
        reduce_only=reduce_only,
        flags='SHORT_TERM',
      )
    case 'LONG_TERM':
      return LongTermOrderParams(
        side=side,
        price=price,
        size=size,
        time_in_force=time_in_force,
        reduce_only=reduce_only,
        flags='LONG_TERM',
      )
    case 'CONDITIONAL':
      return ConditionalOrderParams(
        side=side,
        price=price,
        size=size,
        time_in_force=time_in_force,
        reduce_only=reduce_only,
        flags='CONDITIONAL',
      )


async def with_expiry(
  self: MarketMixin, params: OrderParams, settings: Settings
) -> OrderParams:
  """Apply SDK-configured dYdX order expiry deltas."""
  if (
    params['flags'] == 'SHORT_TERM'
    and (delta := settings.get('short_term_gtb')) is not None
  ):
    latest = await self.client.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None:
      raise ValidationError('Latest dYdX block response did not include a header')
    updated = params.copy()
    updated['good_til_block'] = block.header.height + delta
    return updated
  if (
    params['flags'] in {'LONG_TERM', 'CONDITIONAL'}
    and (delta := settings.get('long_term_gtbt')) is not None
  ):
    latest = await self.client.chain.tendermint.get_latest_block()
    block = latest.block
    if block is None or block.header is None or block.header.time is None:
      raise ValidationError('Latest dYdX block response did not include a timestamp')
    good_til_block_time = int(block.header.time.timestamp()) + delta
    if params['flags'] == 'LONG_TERM':
      updated = params.copy()
      updated['good_til_block_time'] = good_til_block_time
      return updated
    if params['flags'] == 'CONDITIONAL':
      updated = params.copy()
      updated['good_til_block_time'] = good_til_block_time
      return updated
  return params


@wrap_exceptions
async def place_order(
  self: MarketMixin, order: Order, *, settings: MarketSettings = {}
) -> OrderResponse:
  s = settings_adapter.validate_python(settings.get('dydx', {}))
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
async def cancel_orders(
  self: MarketMixin, ids: Sequence[str], *, settings: MarketSettings = {}
) -> CancelResults:
  order_ids = [parse_id(id) for id in ids]
  short_term = [order_id for order_id in order_ids if order_id.order_flags == 0]
  long_term = [order_id for order_id in order_ids if order_id.order_flags != 0]

  results: CancelResults = {}
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
