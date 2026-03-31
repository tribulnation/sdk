from typing_extensions import Any, Sequence
from decimal import Decimal

from trading_sdk.core import ApiError
from trading_sdk.market import Order, OrderResponse, OrderState
from trading_sdk.util import fmt_num

from hyperliquid.exchange.cancel import Cancel as CancelWire
from hyperliquid.exchange.order import Order as OrderWire
from hyperliquid.info.methods.order_status import OrderStatusResponse

from hyperliquid_sdk.core import round_price, wrap_exceptions
from .mixin import SpotMarketMixin, PerpMarketMixin


def _active(status: str) -> bool:
  # conservative: only 'open' is definitely active; 'triggered' is still live too
  return status in {"open", "triggered", "scheduledCancel"}


def _export_order(self: SpotMarketMixin | PerpMarketMixin, o: Order) -> OrderWire:
  if o["type"] == "LIMIT":
    tif = self.settings.get("limit_tif", "Gtc")
  elif o["type"] == "POST_ONLY":
    tif = "Alo"
  else:
    raise ValueError(f"Unknown order type: {o['type']}")

  qty = Decimal(o["qty"])
  price = round_price(Decimal(o["price"]))
  return {
    "a": self.asset_id,
    "b": qty >= 0,
    "p": fmt_num(price),
    "s": fmt_num(abs(qty)),
    "r": self.settings.get("reduce_only", False),
    "t": {"limit": {"tif": tif}},
  }


@wrap_exceptions
async def open_orders(self: SpotMarketMixin | PerpMarketMixin) -> Sequence[OrderState]:
  dex = getattr(self, "dex", None)
  if dex is not None:
    orders = await self.client.info.open_orders(self.address, dex=dex)
  else:
    orders = await self.client.info.open_orders(self.address)

  out: list[OrderState] = []
  for o in orders:
    if o.get("coin") != self.asset_name:
      continue
    qty = Decimal(o["origSz"])
    out.append(
      OrderState(
        id=str(o["oid"]),
        price=Decimal(o["limitPx"]),
        qty=qty,
        filled_qty=qty - Decimal(o["sz"]),
        active=True,
        details=o,
      )
    )
  return out


@wrap_exceptions
async def place_order(self: SpotMarketMixin | PerpMarketMixin, order: Order) -> OrderResponse:
  wire = _export_order(self, order)
  result = await self.client.exchange.order(wire)
  if result["status"] != "ok":
    raise ApiError(result)

  statuses = result["response"]["data"]["statuses"]
  if not statuses:
    raise ApiError({"error": "empty status list", "details": result})

  s = statuses[0]
  if (err := s.get("error")) is not None:
    raise ApiError(err)
  if (resting := s.get("resting")) is not None:
    return OrderResponse(id=str(resting["oid"]), details=s)
  if (filled := s.get("filled")) is not None:
    return OrderResponse(id=str(filled["oid"]), details=s)
  raise ApiError({"error": "unknown order status", "details": s})


@wrap_exceptions
async def cancel_order(self: SpotMarketMixin | PerpMarketMixin, id: str) -> Any:
  cancel: CancelWire = {"a": self.asset_id, "o": int(id)}
  result = await self.client.exchange.cancel(cancel)
  if result["status"] != "ok":
    raise ApiError(result)
  statuses = result["response"]["data"]["statuses"]
  if not statuses:
    raise ApiError({"error": "empty status list", "details": result})
  s = statuses[0]
  if s == "success":
    return s
  if isinstance(s, dict) and (err := s.get("error")) is not None:
    raise ApiError(err)
  raise ApiError({"error": "unknown cancel status", "details": s})


@wrap_exceptions
async def query_order(self: SpotMarketMixin | PerpMarketMixin, id: str) -> OrderState | None:
  status: OrderStatusResponse = await self.client.info.order_status(self.address, int(id))
  if status["status"] == "unknownOid":
    return None

  entry = status["order"]
  o = entry["order"]
  if o.get("coin") != self.asset_name:
    return None

  qty = Decimal(o["origSz"])
  return OrderState(
    id=str(o["oid"]),
    price=Decimal(o["limitPx"]),
    qty=qty,
    filled_qty=qty - Decimal(o["sz"]),
    active=_active(entry["status"]),
    details=status,
  )

