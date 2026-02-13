from typing_extensions import TypedDict, Literal, NotRequired
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

from tribulnation.sdk.core import Num

Side = Literal['BUY', 'SELL']

class BaseOrder(TypedDict):
  qty: Num
  """Quantity of the order in the base asset. Negative -> sell, positive -> buy."""

class LimitOrder(BaseOrder):
  price: Num
  type: Literal['LIMIT']
  post_only: NotRequired[bool]

class MarketOrder(BaseOrder):
  type: Literal['MARKET']

Order = LimitOrder | MarketOrder

@dataclass
class OrderState:
  id: str
  price: Decimal
  qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  filled_qty: Decimal
  """Signed quantity (netagive -> sell, positive -> buy)"""
  active: bool
  time: datetime

  @property
  def side(self) -> Side:
    return 'BUY' if self.qty > 0 else 'SELL'

  @property
  def quote_qty(self) -> Decimal:
    return self.qty * self.price

  @property
  def unfilled_qty(self) -> Decimal:
    return self.qty - self.filled_qty