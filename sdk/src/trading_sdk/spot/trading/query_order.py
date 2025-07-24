from typing_extensions import Protocol, TypedDict, Literal

OrderStatus = Literal['NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED']

class OrderState(TypedDict):
  status: OrderStatus

class QueryOrder(Protocol):
  async def query_order(self, symbol: str, *, id: str) -> OrderState:
    """Query an order.
    
    - `symbol`: The symbol to query the order for.
    - `id`: The ID of the order to query.
    """
    ...