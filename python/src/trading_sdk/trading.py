from typing_extensions import Protocol, TypedDict, Literal, TypeVar, NotRequired, Mapping, overload
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
  
  class PlaceOrder(TypedDict):
    order_id: str

  @overload
  async def place_order(self, symbol: str, order: Order, *, unsafe: Literal[True]) -> PlaceOrder: ...
  @overload
  async def place_order(self, symbol: str, order: Order, *, unsafe: bool = False) -> PlaceOrder | AuthedError: ...

  @overload
  async def cancel_order(self, symbol: str, *, order_id: str, unsafe: Literal[True]) -> None: ...
  @overload
  async def cancel_order(self, symbol: str, *, order_id: str, unsafe: bool = False) -> AuthedError | None: ...

  @overload
  async def cancel_all_orders(self, symbol: str, *, unsafe: Literal[True]) -> None: ...
  @overload
  async def cancel_all_orders(self, symbol: str, *, unsafe: bool = False) -> AuthedError | None: ...

  class QueryOrder(TypedDict):
    status: 'Trading.OrderStatus'
    executed_qty: Decimal

  @overload
  async def query_order(self, symbol: str, *, order_id: str, unsafe: Literal[True]) -> QueryOrder: ...
  @overload
  async def query_order(self, symbol: str, *, order_id: str, unsafe: bool = False) -> QueryOrder | AuthedError: ...

  class Balance(TypedDict):
    free: Decimal
    locked: Decimal

  @overload
  async def get_balances(self, *currencies: S, unsafe: Literal[True]) -> Mapping[S, Balance]: ...
  @overload
  async def get_balances(self, *currencies: S, unsafe: bool = False) -> Mapping[S, Balance] | AuthedError: ...