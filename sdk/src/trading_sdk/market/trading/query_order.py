from typing_extensions import Protocol, Sequence
import asyncio

from trading_sdk.market.types import OrderState
  
class QueryOrder(Protocol):
  async def query_order(self, id: str) -> OrderState:
    """Query an order.
    
    - `id`: The ID of the order to query.
    """
    ...

  async def query_orders(self, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple orders.
    
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.query_order(id) for id in ids])