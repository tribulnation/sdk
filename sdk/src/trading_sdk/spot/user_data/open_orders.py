from typing_extensions import Protocol, Sequence
from .query_order import OrderState

class OpenOrders(Protocol):
  async def open_orders(self, base: str, quote: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...