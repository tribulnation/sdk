from typing_extensions import Protocol, TypedDict, Literal, TypeVar, NotRequired
from decimal import Decimal

from trading_sdk.types import Side, TimeInForce, Num
from trading_sdk.errors import AuthedError

S = TypeVar('S', bound=str)

class Trading(Protocol):

  class BaseOrder(TypedDict):
    side: Side

  class LimitOrder(BaseOrder):
    type: Literal['LIMIT']
    qty: Num
    price: Num
    time_in_force: NotRequired[TimeInForce]
    post_only: NotRequired[bool]


  class MarketOrder(BaseOrder):
    type: Literal['MARKET']
    qty: Num
    time_in_force: NotRequired[TimeInForce]

  Order = LimitOrder | MarketOrder

  OrderStatus = Literal['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED']
  
  class PlaceOrderResponse(TypedDict):
    order_id: str

  async def place_order(self, symbol: str, order: Order) -> PlaceOrderResponse | AuthedError:
    ...

  async def cancel_order(self, symbol: str, *, order_id: str) -> AuthedError | None:
    ...

  async def cancel_all_orders(self, symbol: str) -> AuthedError | None:
    ...

  class QueryOrderResponse(TypedDict):
    status: 'Trading.OrderStatus'
    executed_qty: Decimal

  async def query_order(self, symbol: str, *, order_id: str) -> QueryOrderResponse:
    ...

  class Balance(TypedDict):
    free: Decimal
    locked: Decimal

  async def get_balances(self, *currencies: S) -> dict[S, Balance]:
    ...