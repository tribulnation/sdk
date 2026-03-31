from typing_extensions import Literal, Sequence
from decimal import Decimal
import base64

from dydx.indexer.data.api.list_parent_orders import Order as IndexerOrder
from dydx.node.private.place_order import Order as DydxOrder, TimeInForce
from dydx_v4_client import OrderFlags
from dydx_v4_client.node.builder import TxOptions
from trading_sdk.core import ValidationError
from trading_sdk.market import Order, OrderResponse, OrderState
from v4_proto.dydxprotocol.clob.order_pb2 import OrderId
from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId

from dydx_sdk.core import wrap_exceptions
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


def _protobuf_id(order: IndexerOrder, *, address: str) -> OrderId:
  return OrderId(
    client_id=int(order['clientId']),
    order_flags=int(order['orderFlags']),
    clob_pair_id=int(order['clobPairId']),
    subaccount_id=SubaccountId(
      owner=address,
      number=int(order['subaccountNumber']),
    ),
  )

def serialize_id(order_id: OrderId) -> str:
  return base64.b64encode(order_id.SerializeToString()).decode()


def parse_id(id: str) -> OrderId:
  return OrderId.FromString(base64.b64decode(id))

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
  address = await self.address
  orders = await self.indexer.data.list_parent_orders(
    address=address,
    parent_subaccount=self.settings.get('parent_subaccount', 0),
    ticker=self.market,
    status=status,
  )
  return [parse_state(order, address=address) for order in orders]

def _time_in_force(order: Order, settings: Settings) -> TimeInForce:
  if order['type'] == 'POST_ONLY':
    return 'POST_ONLY'
  return settings.get('limit_tif', 'GOOD_TIL_TIME')

def export_order(order: Order, settings: Settings) -> DydxOrder:
  signed_qty = Decimal(order['qty'])
  side = 'BUY' if signed_qty >= 0 else 'SELL'
  return DydxOrder(
    side=side,
    price=Decimal(order['price']),
    size=abs(signed_qty),
    flags=settings.get('order_flags', 'LONG_TERM'),
    time_in_force=_time_in_force(order, settings),
    reduce_only=settings.get('reduce_only', False),
  )

@wrap_exceptions
async def place_order(self: MarketMixin, order: Order) -> OrderResponse:
  response = await self.client.node.place_order(
    self.perpetual_market,
    export_order(order, self.settings),
    subaccount=self.subaccount,
    gtb_delta=self.settings.get('short_term_gtb'),
    gtbt_delta=self.settings.get('long_term_gtbt'),
  )
  return OrderResponse(
    id=serialize_id(response['order'].order_id),
    details=response,
  )

@wrap_exceptions
async def place_orders(self: MarketMixin, orders: Sequence[Order]) -> Sequence[OrderResponse]:
  results: list[OrderResponse] = []
  tx_options: TxOptions | None = None

  # dYdX long-term orders consume a sequence per tx, so batch placement must stay serial.
  for order in orders:
    response = await self.client.node.place_order(
      self.perpetual_market,
      export_order(order, self.settings),
      subaccount=self.subaccount,
      tx_options=tx_options,
      gtb_delta=self.settings.get('short_term_gtb'),
      gtbt_delta=self.settings.get('long_term_gtbt'),
    )
    if tx_options is None:
      wallet = await self.client.node.wallet
      tx_options = TxOptions(
        sequence=wallet.sequence,
        account_number=wallet.account_number,
        authenticators=[],
      )
    tx_options.sequence += 1
    results.append(OrderResponse(
      id=serialize_id(response['order'].order_id),
      details=response,
    ))

  return results

@wrap_exceptions
async def cancel_order(self: MarketMixin, id: str):
  return await self.client.node.cancel_order(parse_id(id))

@wrap_exceptions
async def cancel_orders(self: MarketMixin, ids: Sequence[str]):
  order_ids = [parse_id(id) for id in ids]
  short_term = [order_id for order_id in order_ids if order_id.order_flags == OrderFlags.SHORT_TERM]
  long_term = [order_id for order_id in order_ids if order_id.order_flags == OrderFlags.LONG_TERM]

  results: dict = {}
  if short_term:
    results['short_term'] = await self.client.node.batch_cancel_orders(short_term)
  if long_term:
    results['long_term'] = []
    tx_options: TxOptions | None = None
    for order_id in long_term:
      results['long_term'].append(await self.client.node.cancel_order(order_id, tx_options=tx_options))
      if tx_options is None:
        wallet = await self.client.node.wallet
        tx_options = TxOptions(
          sequence=wallet.sequence,
          account_number=wallet.account_number,
          authenticators=[],
        )
      tx_options.sequence += 1

  return results

@wrap_exceptions
async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  for order in await list_orders(self):
    if order.id == id:
      return order

@wrap_exceptions
async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  return await list_orders(self, status='OPEN')