from typing_extensions import Protocol, Sequence

from .query_order import OrderState

class OpenOrders(Protocol):
  async def open_orders(self) -> Sequence[OrderState]:
    """Fetch your currently open orders."""
    ...
