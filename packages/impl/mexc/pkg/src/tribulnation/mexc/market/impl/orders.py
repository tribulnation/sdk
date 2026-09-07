from typing_extensions import Literal, Sequence
from decimal import Decimal

from typed_mexc.spot.http.account.open_orders import OpenOrder
from typed_mexc.spot.http.account.order import OrderStatus as MexcOrderStatus
from typed_mexc.spot.http.trade.cancel_order import CancelOrderResponse
from typed_mexc.spot.http.trade.place_order import (
  LimitOrderRequest,
  MarketOrderByQuantityRequest,
)

from tribulnation.sdk.core import ValidationError
from tribulnation.sdk.market import Order, OrderResponse, OrderState, Settings

from tribulnation.mexc.core.exc import wrap_exceptions
from .mixin import MarketMixin

OrderStatus = Literal[
  'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'PARTIALLY_CANCELED'
]
OrderSide = Literal['BUY', 'SELL']
PlaceOrderRequest = LimitOrderRequest | MarketOrderByQuantityRequest


def _active(status: str) -> bool:
  match status:
    case 'NEW' | 'PARTIALLY_FILLED':
      return True
    case 'FILLED' | 'CANCELED' | 'PARTIALLY_CANCELED':
      return False
    case _:
      raise ValidationError(f'Unknown order status: {status}')


def _required(order: OpenOrder | MexcOrderStatus, key: str) -> str:
  value = order.get(key)  # type: ignore[call-overload]
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


def _dump_order(
  symbol: str, order: Order, *, recv_window: int | None
) -> PlaceOrderRequest:
  signed_qty = Decimal(order['qty'])
  side: OrderSide = 'BUY' if signed_qty >= 0 else 'SELL'
  qty = abs(signed_qty)
  request: PlaceOrderRequest
  match order['type']:
    case 'MARKET':
      request = {'symbol': symbol, 'side': side, 'type': 'MARKET', 'quantity': qty}
    case 'LIMIT':
      request = {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT',
        'quantity': qty,
        'price': Decimal(order['price']),
      }
    case 'POST_ONLY':
      request = {
        'symbol': symbol,
        'side': side,
        'type': 'LIMIT_MAKER',
        'quantity': qty,
        'price': Decimal(order['price']),
      }
    case _:
      raise ValidationError(f'Unknown order type: {order["type"]}')
  if recv_window is not None:
    request['recvWindow'] = recv_window
  return request


@wrap_exceptions
async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  orders = await self.client.spot.http.account.open_orders(
    symbol=self.instrument,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  return [_parse_order(o) for o in orders]


@wrap_exceptions
async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  order = await self.client.spot.http.account.order(
    symbol=self.instrument,
    order_id=id,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
  return _parse_order(order)


@wrap_exceptions
async def place_order(
  self: MarketMixin, order: Order, *, settings: Settings = {}
) -> OrderResponse:
  request = _dump_order(self.instrument, order, recv_window=self.shared.recv_window)
  r = await self.client.spot.http.trade.place_order(
    request, validate=self.shared.validate
  )
  return OrderResponse(id=str(r['orderId']), details=r)


@wrap_exceptions
async def cancel_order(
  self: MarketMixin, id: str, *, settings: Settings = {}
) -> CancelOrderResponse:
  return await self.client.spot.http.trade.cancel_order(
    symbol=self.instrument,
    order_id=id,
    recv_window=self.shared.recv_window,
    validate=self.shared.validate,
  )
