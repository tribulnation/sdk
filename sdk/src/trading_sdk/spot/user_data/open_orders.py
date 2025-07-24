from typing_extensions import Protocol, TypedDict, Sequence
from decimal import Decimal
from datetime import datetime
from trading_sdk.types import Side

class OrderState(TypedDict):
  id: str
  price: Decimal
  quantity: Decimal
  filled_quantity: Decimal
  time: datetime
  side: Side

class OpenOrders(Protocol):
  async def open_orders(self, symbol: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given symbol.
    
    - `symbol`: The symbol being traded, e.g. `BTCUSDT`
    """
    ...