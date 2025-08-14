from abc import ABC, abstractmethod
from typing_extensions import Sequence
from .query_order import OrderState

class OpenOrders(ABC):
  @abstractmethod
  async def open_orders(self, base: str, quote: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...