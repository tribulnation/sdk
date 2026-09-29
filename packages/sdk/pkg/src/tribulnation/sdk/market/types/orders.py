from typing_extensions import Any, TypedDict, Literal, NotRequired
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.util import Num


class Order(TypedDict):
  qty: Num
  """Quantity of the order in the base asset. Negative -> sell, positive -> buy."""
  price: Num
  type: Literal['MARKET', 'LIMIT', 'POST_ONLY']
  """Market orders are only partially supported. If not supported, the market will place a limit order at the indicated price."""
  client_order_id: NotRequired[str | None]
  """Your own ID for the order, sent unchanged as the venue's client order ID and reported back on its fills as `Trade.client_order_id`. Format and uniqueness rules are the venue's; `Market.random_client_order_id()` generates a valid one. `None` is the same as leaving it out. Venues without client order IDs ignore it."""


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
