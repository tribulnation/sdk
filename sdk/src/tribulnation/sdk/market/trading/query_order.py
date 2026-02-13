from typing_extensions import Sequence
from abc import abstractmethod
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.market.types import OrderState
  
class QueryOrder(SDK):
  @SDK.method
  @abstractmethod
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