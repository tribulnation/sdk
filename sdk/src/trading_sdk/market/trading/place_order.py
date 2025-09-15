from typing_extensions import Protocol, Sequence
import asyncio

from trading_sdk.market.types import Order

class PlaceOrder(Protocol):
  async def place_order(self, instrument: str, /, *, order: Order) -> str:
    """Place an order.
    
    - `instrument`: The instrument to place the order on.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...

  async def place_orders(self, instrument: str, /, *, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    return await asyncio.gather(*[self.place_order(instrument, order=order) for order in orders])

class SpotPlaceOrder(PlaceOrder, Protocol):
  async def spot_place_order(self, base: str, quote: str, /, *, order: Order) -> str:
    """Place an order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...

  async def spot_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    return await asyncio.gather(*[self.spot_place_order(base, quote, order=order) for order in orders])

class PerpPlaceOrder(PlaceOrder, Protocol):
  async def perp_place_order(self, base: str, quote: str, /, *, order: Order) -> str:
    """Place an order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...

  async def perp_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    return await asyncio.gather(*[self.perp_place_order(base, quote, order=order) for order in orders])

class InversePerpPlaceOrder(PlaceOrder, Protocol):
  async def inverse_perp_place_order(self, currency: str, /, *, order: Order) -> str:
    """Place an order on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `order`: The order to place.
    """
    ...

  async def inverse_perp_place_orders(self, currency: str, /, *, orders: Sequence[Order]) -> Sequence[str]:
    """Place multiple orders on a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `orders`: The orders to place.
    """
    ...