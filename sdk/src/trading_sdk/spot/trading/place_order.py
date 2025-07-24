from typing_extensions import Protocol, TypedDict, Literal, NotRequired
from trading_sdk.types import Side, TimeInForce

class BaseOrder(TypedDict):
  side: Side
  time_in_force: NotRequired[TimeInForce]
  quantity: str
  """Quantity of the order in the base asset."""

class LimitOrder(BaseOrder):
  type: Literal['LIMIT']
  price: str

class MarketOrder(BaseOrder):
  type: Literal['MARKET']

Order = LimitOrder | MarketOrder

class Response(TypedDict):
  id: str

class PlaceOrder(Protocol):
  async def place_order(self, symbol: str, order: Order) -> Response:
    """Place an order.
    
    - `symbol`: The symbol to place the order for.
    - `order`: The order to place.
    """
    ...