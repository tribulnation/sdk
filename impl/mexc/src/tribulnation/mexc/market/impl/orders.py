from typing_extensions import Literal, NotRequired, Required, Sequence, TypedDict
from decimal import Decimal

from mexc.spot.account.open_orders import OpenOrder
from mexc.spot.account.order import OrderStatus as MexcOrderStatus
from mexc.spot.trade.cancel_order import CancelOrderResponse
from mexc.spot.trade.place_order import PlaceOrderResponse

from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin

OrderStatus = Literal['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'PARTIALLY_CANCELED']
OrderSide = Literal['BUY', 'SELL']
MexcOrderType = Literal['LIMIT', 'MARKET', 'LIMIT_MAKER']

class DumpedOrder(TypedDict):
  side: Required[OrderSide]
  type_: Required[MexcOrderType]
  quantity: Required[str]
  price: NotRequired[str]

def _active(status: str) -> bool:
  match status:
    case "NEW" | "PARTIALLY_FILLED":
      return True
    case "FILLED" | "CANCELED" | "PARTIALLY_CANCELED":
      return False
    case _:
      raise ValidationError(f"Unknown order status: {status}")


def _required(order: OpenOrder | MexcOrderStatus, key: str) -> str:
  value = order.get(key) # type: ignore[call-overload]
  if value is None:
    raise ValidationError(f'Missing order field: {key}')
  return str(value)


def _parse_order(order: OpenOrder | MexcOrderStatus) -> OrderState:
  sign = 1 if _required(order, 'side') == 'BUY' else -1
  return OrderState(
    id=_required(order, 'orderId'),
    price=Decimal(_required(order, 'price')),
    qty=Decimal(_required(order, 'origQty')) * sign,
    filled_qty=Decimal(_required(order, 'executedQty')) * sign,
    active=_active(_required(order, 'status')),
    details=order,
  )


def _dump_order(order: Order) -> DumpedOrder:
  signed_qty = Decimal(order['qty'])
  side: OrderSide = 'BUY' if signed_qty >= 0 else 'SELL'
  qty = str(abs(signed_qty))

  match order['type']:
    case 'MARKET':
      return {'type_': 'MARKET', 'side': side, 'quantity': qty}
    case 'LIMIT':
      return {'type_': 'LIMIT', 'side': side, 'price': str(order['price']), 'quantity': qty}
    case 'POST_ONLY':
      return {'type_': 'LIMIT_MAKER', 'side': side, 'price': str(order['price']), 'quantity': qty}
    case _:
      raise ValidationError(f"Unknown order type: {order['type']}")


@wrap_exceptions
async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  orders = await self.client.spot.account.open_orders(
    symbol=self.instrument,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  return [_parse_order(o) for o in orders]


@wrap_exceptions
async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  order = await self.client.spot.account.order(
    symbol=self.instrument,
    order_id=id,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  return _parse_order(order)


@wrap_exceptions
async def place_order(self: MarketMixin, order: Order, *, settings: Settings = {}) -> OrderResponse:
  dumped = _dump_order(order)
  r: PlaceOrderResponse = await self.client.spot.trade.place_order(
    symbol=self.instrument,
    side=dumped['side'],
    type_=dumped['type_'],
    quantity=dumped['quantity'],
    price=dumped.get('price'),
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  return OrderResponse(id=str(r.get('orderId')), details=r)


@wrap_exceptions
async def cancel_order(self: MarketMixin, id: str, *, settings: Settings = {}) -> CancelOrderResponse:
  return await self.client.spot.trade.cancel_order(
    symbol=self.instrument,
    order_id=id,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
