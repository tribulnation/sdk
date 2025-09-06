from typing_extensions import Protocol

from trading_sdk.types import Num

class EditOrder(Protocol):
  async def edit_order(self, instrument: str, /, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order.
    
    - `instrument`: The instrument to edit the order on.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.

    Returns the new ID of the order.
    """
    ...

class SpotEditOrder(EditOrder, Protocol):
  async def spot_edit_order(self, base: str, quote: str, /, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.

    Returns the new ID of the order.
    """
    ...

class PerpEditOrder(EditOrder, Protocol):
  async def perp_edit_order(self, base: str, quote: str, /, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.

    Returns the new ID of the order.
    """
    ...

class InversePerpEditOrder(EditOrder, Protocol):
  async def inverse_perp_edit_order(self, currency: str, /, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order on a inverse perpetual instrument.
    
    - `currency`: The currency, e.g. `BTC`.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.
    
    Returns the new ID of the order.
    """
    ...