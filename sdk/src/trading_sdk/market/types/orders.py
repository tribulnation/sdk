from typing_extensions import Any, TypedDict, Literal
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.util import Num

class Order(TypedDict):
  qty: Num
  """Quantity of the order in the base asset. Negative -> sell, positive -> buy."""
  price: Num
  type: Literal['MARKET', 'LIMIT', 'POST_ONLY']
  """Market orders are only partially supported. If not supported, the market will place a limit order at the indicated price."""

@dataclass(kw_only=True)
class OrderResponse:
  id: str
  details: Any = None

@dataclass(kw_only=True)
class OrderState:
  id: str
  price: Decimal
  qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  filled_qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  active: bool
  """Whether the order is active in the market."""
  details: Any = None