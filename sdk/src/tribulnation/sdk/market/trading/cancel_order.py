from typing_extensions import Sequence
from abc import abstractmethod
import asyncio

from tribulnation.sdk import SDK
from tribulnation.sdk.market.types import OrderState

class CancelOrder(SDK):
  @SDK.method
  @abstractmethod
  async def cancel_order(self, id: str) -> OrderState:
    """Cancel an order.
    
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...

  async def cancel_orders(self, ids: Sequence[str]) -> Sequence[OrderState]:
    """Cancel multiple orders.
    
    - `ids`: The IDs of the orders to cancel.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.cancel_order(id=id) for id in ids])
