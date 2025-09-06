from typing_extensions import Protocol, Sequence

from .query_order import OrderState

class OpenOrders(Protocol):
  async def open_orders(self, instrument: str, /) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given instrument.
    
    - `instrument`: The instrument to get the open orders for.
    """
    ...

class SpotOpenOrders(OpenOrders, Protocol):
  async def spot_open_orders(self, base: str, quote: str, /) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...

class PerpOpenOrders(OpenOrders, Protocol):
  async def perp_open_orders(self, base: str, quote: str, /) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    ...

class InversePerpOpenOrders(OpenOrders, Protocol):
  async def inverse_perp_open_orders(self, currency: str, /) -> Sequence[OrderState]:
    """Fetch currently open orders (of your account) on a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    """
    ...