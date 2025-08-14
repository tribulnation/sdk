from abc import ABC, abstractmethod
from trading_sdk.types import Num

class EditOrder(ABC):
  @abstractmethod
  async def edit_order(self, base: str, quote: str, *, id: str, qty: Num) -> str:
    """Edit an existing order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to edit.
    - `quantity`: The new quantity of the order.

    Returns the new ID of the order.
    """
    ...