from typing_extensions import TypedDict, Literal, Sequence
from abc import abstractmethod
import asyncio

from tribulnation.sdk.core import Num, SDK


class Place(SDK):
  class BaseOrder(TypedDict):
    qty: Num
    """Quantity of the order in the base asset. Negative -> sell, positive -> buy."""

  class LimitOrder(BaseOrder):
    price: Num
    type: Literal['LIMIT', 'POST_ONLY']

  class MarketOrder(BaseOrder):
    type: Literal['MARKET']

  Order = LimitOrder | MarketOrder
  
  @SDK.method
  @abstractmethod
  async def order(self, order: Order) -> str:
    """Place an order and return the order ID."""
  
  @SDK.method
  async def orders(self, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders and return the order IDs."""
    return await asyncio.gather(*[self.order(order) for order in orders])