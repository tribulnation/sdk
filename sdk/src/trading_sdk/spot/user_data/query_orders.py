import asyncio
from typing_extensions import Sequence, Protocol
from .query_order import QueryOrder, OrderState

class QueryOrders(QueryOrder, Protocol):
  async def query_orders(self, base: str, quote: str, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple orders by symbol and ID.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to query.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.query_order(base, quote, id=id) for id in ids])