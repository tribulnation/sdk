from typing_extensions import Protocol, TypeVar
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.util import trunc2tick
from trading_sdk.market.types import Instrument

S = TypeVar('S', bound=str)

@dataclass
class Info:
  tick_size: Decimal
  """Tick size of the price (in quote units)."""
  step_size: Decimal
  """Step size of the quantity (in base units)."""
  min_qty_: Decimal | None = None
  """Minimum quantity of the order (in base units)."""
  max_qty: Decimal | None = None
  """Maximum quantity of the order (in base units)."""
  min_price: Decimal | None = None
  """Minimum price of the order (in quote units)."""
  max_price: Decimal | None = None
  """Maximum price of the order (in quote units)."""

  @property
  def min_qty(self) -> Decimal:
    """Minimum quantity of the order (in base units)."""
    return self.min_qty_ or self.step_size
  
  def trunc_qty(self, base_qty: Decimal) -> Decimal | None:
    """Truncate the (base asset) quantity to the nearest step size. Returns `None` if the quantity is too small."""
    qty = trunc2tick(base_qty, self.step_size)
    if qty > self.min_qty:
      return qty
  
  def amount2qty(self, quote_amount: Decimal, *, price: Decimal) -> Decimal | None:
    """Convert a quote amount to a base quantity, truncating to the nearest step size. Returns `None` if the quantity is too small."""
    return self.trunc_qty(quote_amount / price)
  
  def qty2amount(self, base_qty: Decimal, *, price: Decimal) -> Decimal:
    """Convert a base quantity to a quote amount."""
    return base_qty * price
  
class ExchangeInfo(Protocol):
  async def exchange_info(self, instrument: Instrument) -> Info:
    """Get the exchange info for the given symbol.
    
    - `instrument`: The instrument to get the exchange info for.
    """
    ...

  async def exchange_info_any(self, instrument: str) -> Info:
    """Get the exchange info for the given instrument by the exchange-specific name.
    
    - `instrument`: The name of the instrument to get the exchange info for.
    """
    return await self.exchange_info({'type': 'any', 'name': instrument})
  
  async def exchange_info_spot(self, base: str, quote: str) -> Info:
    """Get the exchange info for the given spot instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    return await self.exchange_info({'type': 'spot', 'base': base, 'quote': quote})
  
  async def exchange_info_perp(self, base: str, quote: str) -> Info:
    """Get the exchange info for the given perpetual instrument.
    
    - `base`: The base asset, e.g. `BTC`.
    - `quote`: The quote asset, e.g. `USDT`.
    """
    return await self.exchange_info({'type': 'perp', 'base': base, 'quote': quote})