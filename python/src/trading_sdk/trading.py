from typing_extensions import Protocol, TypedDict, Literal, TypeVar, NotRequired, Mapping
from decimal import Decimal

from trading_sdk.types import Side, TimeInForce, Num

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
  
  class PlaceOrder(TypedDict):
    order_id: str

  async def place_order(self, symbol: str, order: Order) -> PlaceOrder: ...

  async def cancel_order(self, symbol: str, *, order_id: str) -> None: ...

  async def cancel_all_orders(self, symbol: str) -> None: ...

  class QueryOrder(TypedDict):
    status: 'Trading.OrderStatus'
    executed_qty: Decimal

  async def query_order(self, symbol: str, *, order_id: str) -> QueryOrder: ...

  class Balance(TypedDict):
    free: Decimal
    locked: Decimal

  async def get_balances(self, *currencies: S) -> Mapping[S, Balance]: ...