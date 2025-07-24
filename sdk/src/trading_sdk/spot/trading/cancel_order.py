from typing_extensions import Protocol

class CancelOrder(Protocol):
  async def cancel_order(self, symbol: str, *, id: str):
    """Cancel an order.
    
    - `symbol`: The symbol to cancel the order for.
    - `id`: The ID of the order to cancel.
    """
    ...