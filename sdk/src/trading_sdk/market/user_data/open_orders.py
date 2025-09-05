from typing_extensions import Protocol, Sequence

from trading_sdk.market.types import Instrument
from .query_order import OrderState

class OpenOrders(Protocol):
  async def open_orders(self, instrument: Instrument) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given instrument.
    
    - `instrument`: The instrument to get the open orders for.
    """
    ...

  async def open_orders_any(self, instrument: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the open orders for.
    """
    return await self.open_orders({'type': 'any', 'name': instrument})
  
  async def open_orders_spot(self, base: str, quote: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given spot instrument.

    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    return await self.open_orders({'type': 'spot', 'base': base, 'quote': quote})
  
  async def open_orders_perp(self, base: str, quote: str) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    return await self.open_orders({'type': 'perp', 'base': base, 'quote': quote})