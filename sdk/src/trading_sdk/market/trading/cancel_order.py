from typing_extensions import Protocol, Sequence
import asyncio

from trading_sdk.market.user_data.query_order import OrderState

class CancelOrder(Protocol):
  async def cancel_order(self, instrument: str, /, *, id: str) -> OrderState:
    """Cancel an order.
    
    - `instrument`: The instrument to cancel the order on.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...

  async def cancel_orders(self, instrument: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Cancel multiple orders.
    
    - `instrument`: The instrument to cancel the orders on.
    - `ids`: The IDs of the orders to cancel.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.cancel_order(instrument, id=id) for id in ids])


class SpotCancelOrder(CancelOrder, Protocol):
  async def spot_cancel_order(self, base: str, quote: str, /, *, id: str) -> OrderState:
    """Cancel an order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...

  async def spot_cancel_orders(self, base: str, quote: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Cancel multiple orders on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to cancel.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.spot_cancel_order(base, quote, id=id) for id in ids])


class PerpCancelOrder(CancelOrder, Protocol):
  async def perp_cancel_order(self, base: str, quote: str, /, *, id: str) -> OrderState:
    """Cancel an order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...

  async def perp_cancel_orders(self, base: str, quote: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Cancel multiple orders on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `ids`: The IDs of the orders to cancel.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.perp_cancel_order(base, quote, id=id) for id in ids])


class InversePerpCancelOrder(CancelOrder, Protocol):
  async def inverse_perp_cancel_order(self, currency: str, /, *, id: str) -> OrderState:
    """Cancel an order on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `id`: The ID of the order to cancel.

    Returns the state of the order.
    """
    ...

  async def inverse_perp_cancel_orders(self, currency: str, /, *, ids: Sequence[str]) -> Sequence[OrderState]:
    """Cancel multiple orders on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `ids`: The IDs of the orders to cancel.

    Returns the states of the orders.
    """
    return await asyncio.gather(*[self.inverse_perp_cancel_order(currency, id=id) for id in ids])