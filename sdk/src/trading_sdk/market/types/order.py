from typing_extensions import TypedDict, Literal, NotRequired
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from trading_sdk.types import Num

Side = Literal['BUY', 'SELL']

class BaseOrder(TypedDict):
  side: Side
  qty: Num
  """Quantity of the order in the base asset."""

class LimitOrder(BaseOrder):
  price: Num
  type: Literal['LIMIT']
  post_only: NotRequired[bool]

class MarketOrder(BaseOrder):
  type: Literal['MARKET']

Order = LimitOrder | MarketOrder



OrderStatus = Literal['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'PARTIALLY_CANCELED', 'UNTRIGGERED']

@dataclass
class OrderState:
  id: str
  price: Decimal
  qty: Decimal
  filled_qty: Decimal
  side: Side
  status: OrderStatus
  time: datetime

  @property
  def quote_qty(self) -> Decimal:
    return self.qty * self.price

  @property
  def unfilled_qty(self) -> Decimal:
    return self.qty - self.filled_qty