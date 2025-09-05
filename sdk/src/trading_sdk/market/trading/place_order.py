from typing_extensions import Protocol

from trading_sdk.market.types import Instrument, Order

class PlaceOrder(Protocol):
  async def place_order(self, instrument: Instrument, order: Order, /) -> str:
    """Place an order.
    
    - `instrument`: The instrument to place the order on.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...

  async def place_order_any(self, instrument: str, /, order: Order) -> str:
    """Place an order on any instrument by the exchange-specific name.

    - `instrument`: The name of the instrument to place the order on.
    - `order`: The order to place.

    Returns the order ID.
    """
    return await self.place_order({'type': 'any', 'name': instrument}, order)

  async def place_order_spot(self, base: str, quote: str, /, order: Order) -> str:
    """Place an order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    return await self.place_order({'type': 'spot', 'base': base, 'quote': quote}, order)
  
  async def place_order_perp(self, base: str, quote: str, /, order: Order) -> str:
    """Place an order on a perpetual instrument.
    
    - `base`: The base (underlying) asset, e.g. `BTC`.
    - `quote`: The quote (settlement) asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    return await self.place_order({'type': 'perp', 'base': base, 'quote': quote}, order)