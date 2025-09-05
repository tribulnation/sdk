from typing_extensions import TypedDict, Literal
from trading_sdk.types import Num

Side = Literal['BUY', 'SELL']

class BaseOrder(TypedDict):
  side: Side
  qty: Num
  """Quantity of the order in the base asset."""

class LimitOrder(BaseOrder):
  price: Num
  type: Literal['LIMIT']

class MarketOrder(BaseOrder):
  type: Literal['MARKET']

Order = LimitOrder | MarketOrder
