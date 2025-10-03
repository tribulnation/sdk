from typing_extensions import Protocol, Sequence, Literal, overload
import asyncio

from trading_sdk.market.types import Order, OrderState

ResponseModel = Literal['id', 'state']

class PlaceOrder(Protocol):
  @overload
  async def place_order(
    self, instrument: str, /, *, order: Order,
    response: Literal['id'] = 'id'
  ) -> str:
    """Place an order.
    
    - `instrument`: The instrument to place the order on.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...
  @overload
  async def place_order(
    self, instrument: str, /, *, order: Order,
    response: Literal['state']
  ) -> OrderState:
    """Place an order.
    
    - `instrument`: The instrument to place the order on.
    - `order`: The order to place.

    Returns the order state.
    """
    ...
  async def place_order(
    self, instrument: str, /, *, order: Order,
    response: Literal['id', 'state'] = 'id'
  ) -> str | OrderState:
    return await self._place_order(instrument, order=order, response=response)
  
  async def _place_order(
    self, instrument: str, /, *, order: Order,
    response: Literal['id', 'state'] = 'id'
  ) -> str | OrderState:
    ...

  @overload
  async def place_orders(
    self, instrument: str, /, *, orders: Sequence[Order],
    response: Literal['id'] = 'id'
  ) -> Sequence[str]:
    """Place multiple orders on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    ...
  @overload
  async def place_orders(
    self, instrument: str, /, *, orders: Sequence[Order],
    response: Literal['state']
  ) -> Sequence[OrderState]:
    """Place multiple orders on a given symbol.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order states.
    """
    ...
  async def place_orders(
    self, instrument: str, /, *, orders: Sequence[Order],
    response: Literal['id', 'state'] = 'id'
  ) -> Sequence[str] | Sequence[OrderState]:
    return await asyncio.gather(*[self.place_order(instrument, order=order, response=response) for order in orders]) # type: ignore

class SpotPlaceOrder(PlaceOrder, Protocol):
  @overload
  async def spot_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id'] = 'id') -> str:
    """Place an order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...
  @overload
  async def spot_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['state']) -> OrderState:
    """Place an order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order state.
    """
    ...
  async def spot_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    return await self._spot_place_order(base, quote, order=order, response=response)
  
  async def _spot_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    ...

  @overload
  async def spot_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['id'] = 'id') -> Sequence[str]:
    """Place multiple orders on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    ...
  @overload
  async def spot_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['state']) -> Sequence[OrderState]:
    """Place multiple orders on a given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order states.
    """
    ...
  async def spot_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['id', 'state'] = 'id') -> Sequence[str] | Sequence[OrderState]:
    """Place multiple orders on a given spot instrument."""
    return await asyncio.gather(*[self.spot_place_order(base, quote, order=order, response=response) for order in orders]) # type: ignore

class PerpPlaceOrder(PlaceOrder, Protocol):
  @overload
  async def perp_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id'] = 'id') -> str:
    """Place an order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...
  @overload
  async def perp_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['state']) -> OrderState:
    """Place an order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `order`: The order to place.

    Returns the order state.
    """
    ...
  async def perp_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    return await self._perp_place_order(base, quote, order=order, response=response)
  
  async def _perp_place_order(self, base: str, quote: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    ...

  @overload
  async def perp_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['id'] = 'id') -> Sequence[str]:
    """Place multiple orders on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    ...

  @overload
  async def perp_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['state']) -> Sequence[OrderState]:
    """Place multiple orders on a given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `orders`: The orders to place.

    Returns the order states.
    """
    ...
  async def perp_place_orders(self, base: str, quote: str, /, *, orders: Sequence[Order], response: Literal['id', 'state'] = 'id') -> Sequence[str] | Sequence[OrderState]:
    """Place multiple orders on a given perpetual instrument."""
    return await asyncio.gather(*[self.perp_place_order(base, quote, order=order, response=response) for order in orders]) # type: ignore


class InversePerpPlaceOrder(PlaceOrder, Protocol):
  @overload
  async def inverse_perp_place_order(self, currency: str, /, *, order: Order, response: Literal['id'] = 'id') -> str:
    """Place an order on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `order`: The order to place.

    Returns the order ID.
    """
    ...
  @overload
  async def inverse_perp_place_order(self, currency: str, /, *, order: Order, response: Literal['state']) -> OrderState:
    """Place an order on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `order`: The order to place.

    Returns the order state.
    """
    ...
  async def inverse_perp_place_order(self, currency: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    return await self._inverse_perp_place_order(currency, order=order, response=response)
  
  async def _inverse_perp_place_order(self, currency: str, /, *, order: Order, response: Literal['id', 'state'] = 'id') -> str | OrderState:
    ...

  @overload
  async def inverse_perp_place_orders(self, currency: str, /, *, orders: Sequence[Order], response: Literal['id'] = 'id') -> Sequence[str]:
    """Place multiple orders on a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `orders`: The orders to place.

    Returns the order IDs.
    """
    ...
  @overload
  async def inverse_perp_place_orders(self, currency: str, /, *, orders: Sequence[Order], response: Literal['state']) -> Sequence[OrderState]:
    """Place multiple orders on a given inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `orders`: The orders to place.

    Returns the order states.
    """
    ...
  async def inverse_perp_place_orders(self, currency: str, /, *, orders: Sequence[Order], response: Literal['id', 'state'] = 'id') -> Sequence[str] | Sequence[OrderState]:
    """Place multiple orders on a given inverse perpetual instrument."""
    return await asyncio.gather(*[self.inverse_perp_place_order(currency, order=order, response=response) for order in orders]) # type: ignore