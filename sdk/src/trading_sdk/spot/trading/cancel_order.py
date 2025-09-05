from typing_extensions import Protocol
from trading_sdk.spot.user_data.query_order import OrderState

class CancelOrder(Protocol):
  async def cancel_order(self, base: str, quote: str, *, id: str) -> OrderState:
    """Cancel an order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...