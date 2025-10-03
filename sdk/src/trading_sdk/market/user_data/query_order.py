from typing_extensions import Protocol, Sequence
import asyncio

from trading_sdk.market.types import OrderState
  
class QueryOrder(Protocol):
  async def query_order(self, instrument: str, /, *, id: str) -> OrderState:
    """Query an order.
    
    - `instrument`: The instrument to query the order for.
    - `id`: The ID of the order to query.
    """
    ...

  async def query_orders(self, instrument: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple orders.
    
    - `instrument`: The instrument to query the orders for.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.query_order(instrument, id=id) for id in ids])


class SpotQueryOrder(QueryOrder, Protocol):
  async def spot_query_order(self, base: str, quote: str, /, *, id: str) -> OrderState:
    """Query a spot order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to query.
    """
    ...

  async def spot_query_orders(self, base: str, quote: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple spot orders.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.spot_query_order(base, quote, id=id) for id in ids])

class PerpQueryOrder(QueryOrder, Protocol):
  async def perp_query_order(self, base: str, quote: str, /, *, id: str) -> OrderState:
    """Query a perpetual order.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to query.
    """
    ...

  async def perp_query_orders(self, base: str, quote: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple perpetual orders.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.perp_query_order(base, quote, id=id) for id in ids])


class InversePerpQueryOrder(QueryOrder, Protocol):
  async def inverse_perp_query_order(self, currency: str, /, *, id: str) -> OrderState:
    """Query a inverse perpetual order.
    
    - `currency`: The currency, e.g. `BTC`.
    - `id`: The ID of the order to query.
    """
    ...

  async def inverse_perp_query_orders(self, currency: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Query multiple inverse perpetual orders.
    
    - `currency`: The currency, e.g. `BTC`.
    - `ids`: The IDs of the orders to query.
    """
    return await asyncio.gather(*[self.inverse_perp_query_order(currency, id=id) for id in ids])