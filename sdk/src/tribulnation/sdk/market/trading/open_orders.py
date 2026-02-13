from typing_extensions import Sequence
from abc import abstractmethod

from tribulnation.sdk import SDK
from .query_order import OrderState

class OpenOrders(SDK):  
  @SDK.method
  @abstractmethod
  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    ...
