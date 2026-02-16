from typing_extensions import TypedDict, Literal, Sequence, Any
from abc import abstractmethod
from dataclasses import dataclass
import asyncio

from trading_sdk.core import Num, SDK


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

  @dataclass(kw_only=True)
  class Result:
    id: str
    details: Any = None
  
  @SDK.method
  @abstractmethod
  async def order(self, order: Order) -> Result:
    """Place an order in the market."""
  
  @SDK.method
  async def orders(self, orders: Sequence[Order]) -> Sequence[Result]:
    """Place multiple orders in the market."""
    return await asyncio.gather(*[self.order(order) for order in orders])