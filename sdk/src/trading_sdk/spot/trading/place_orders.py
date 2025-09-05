from typing_extensions import Protocol, Sequence
import asyncio
from .place_order import Order, PlaceOrder

class PlaceOrders(PlaceOrder, Protocol):
  async def place_orders(self, base: str, quote: str, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    return await asyncio.gather(*[self.place_order(base, quote, order) for order in orders])