import asyncio
from typing_extensions import Sequence, Protocol

from trading_sdk.market.types import Instrument
from .query_order import QueryOrder, OrderState

class QueryOrders(QueryOrder, Protocol):
  async def query_orders(self, instrument: Instrument, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple orders by symbol and ID.
    
    - `instrument`: The instrument to query the orders for.
    - `ids`: The IDs of the orders to query.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.query_order(instrument, id=id) for id in ids])
  
  async def query_orders_any(self, instrument: str, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple orders by instrument by the exchange-specific name and ID.
    
    - `instrument`: The name of the instrument to query the orders for.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.query_order({'type': 'any', 'name': instrument}, id=id) for id in ids])
  
  async def query_orders_spot(self, base: str, quote: str, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple spot orders by instrument and ID.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.query_order({'type': 'spot', 'base': base, 'quote': quote}, id=id) for id in ids])

  async def query_orders_perp(self, base: str, quote: str, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple perpetual orders by instrument and ID.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.query_order({'type': 'perp', 'base': base, 'quote': quote}, id=id) for id in ids])