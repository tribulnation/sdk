from typing_extensions import Protocol

from trading_sdk.market.types import Instrument
from trading_sdk.market.user_data.query_order import OrderState

class CancelOrder(Protocol):
  async def cancel_order(self, instrument: Instrument, *, id: str) -> OrderState:
    """Cancel an order.
    
    - `instrument`: The instrument to cancel the order on.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...