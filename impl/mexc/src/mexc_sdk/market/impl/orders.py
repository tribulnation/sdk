from typing_extensions import Any, Sequence
from decimal import Decimal

from trading_sdk.core import ValidationError
from trading_sdk.market import Order, OrderResponse, OrderState

from mexc.core import OrderStatus
from mexc.spot.user_data.query_order import OrderState as MexcOrderState
from mexc.spot.trading.place_order import LimitOrder, Order as MexcOrder

from mexc_sdk.core.exc import wrap_exceptions
from .mixin import MarketMixin


def _active(status: OrderStatus) -> bool:
  match status:
    case "NEW" | "PARTIALLY_FILLED":
      return True
    case "FILLED" | "CANCELED" | "PARTIALLY_CANCELED":
      return False
    case _:
      raise ValidationError(f"Unknown order status: {status}")


def _parse_order(order: MexcOrderState) -> OrderState:
  sign = 1 if order["side"] == "BUY" else -1
  return OrderState(
    id=order["orderId"],
    price=Decimal(order["price"]),
    qty=Decimal(order["origQty"]) * sign,
    filled_qty=Decimal(order["executedQty"]) * sign,
    active=_active(order["status"]),
    details=order,
  )


def _dump_order(order: Order) -> MexcOrder:
  signed_qty = Decimal(order["qty"])
  side = "BUY" if signed_qty >= 0 else "SELL"
  qty = str(abs(signed_qty))

  match order["type"]:
    case "LIMIT":
      return LimitOrder(type="LIMIT", side=side, price=str(order["price"]), quantity=qty)
    case "POST_ONLY":
      return LimitOrder(type="LIMIT_MAKER", side=side, price=str(order["price"]), quantity=qty)
    case other:
      raise ValidationError(f"Unknown order type: {other}")


@wrap_exceptions
async def open_orders(self: MarketMixin) -> Sequence[OrderState]:
  orders = await self.client.spot.open_orders(
    self.instrument,
    recvWindow=self.shared.recvWindow,
    validate=self.shared.validate,
  )
  return [_parse_order(o) for o in orders]


@wrap_exceptions
async def query_order(self: MarketMixin, id: str) -> OrderState | None:
  order = await self.client.spot.query_order(
    self.instrument,
    orderId=id,
    recvWindow=self.shared.recvWindow,
    validate=self.shared.validate,
  )
  return _parse_order(order)


@wrap_exceptions
async def place_order(self: MarketMixin, order: Order) -> OrderResponse:
  r = await self.client.spot.place_order(
    self.instrument,
    _dump_order(order),
    recvWindow=self.shared.recvWindow,
    validate=self.shared.validate,
  )
  return OrderResponse(id=r["orderId"], details=r)


@wrap_exceptions
async def cancel_order(self: MarketMixin, id: str) -> Any:
  return await self.client.spot.cancel_order(
    self.instrument,
    orderId=id,
    recvWindow=self.shared.recvWindow,
    validate=self.shared.validate,
  )

