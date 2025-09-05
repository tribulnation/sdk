from typing_extensions import Protocol

from trading_sdk.types import Num
from trading_sdk.market.types import Instrument

class EditOrder(Protocol):
  async def edit_order(self, instrument: Instrument, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order.
    
    - `instrument`: The instrument to edit the order on.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.

    Returns the new ID of the order.
    """
    ...

  async def edit_order_any(self, instrument: str, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order by the exchange-specific name.
    
    - `instrument`: The name of the instrument to edit the order on.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.
    """

  async def edit_order_spot(self, base: str, quote: str, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order on a spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.
    """
  
  async def edit_order_perp(self, base: str, quote: str, *, id: str, qty: Num | None = None, price: Num | None = None) -> str:
    """Edit an existing order on a perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    - `id`: The ID of the order to edit.
    - `qty`: The new quantity of the order.
    - `price`: The new price of the order.
    """