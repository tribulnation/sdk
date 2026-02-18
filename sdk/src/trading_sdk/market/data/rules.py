from typing_extensions import Any
from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from trading_sdk.core import SDK, trunc2tick, round2tick

class Rules(SDK):
  @dataclass(kw_only=True)
  class Rules:
    """Market rules type."""
    base: str
    """Base asset of the instrument."""
    quote: str
    """Quote asset of the instrument."""
    fee_asset: str
    """Asset used for fees/funding payments."""
    tick_size: Decimal
    """Tick size of the price (in quote units)."""
    step_size: Decimal
    """Step size of the quantity (in base units)."""
    min_qty_: Decimal | None = None
    """Minimum quantity of the order (in base units)."""
    min_value: Decimal | None = None
    """Minimum value of the order (in quote units)."""
    max_qty: Decimal | None = None
    """Maximum quantity of the order (in base units)."""
    min_price: Decimal | None = None
    """Minimum price of the order (in quote units)."""
    max_price: Decimal | None = None
    """Maximum price of the order (in quote units)."""
    maker_fee: Decimal
    """Maker fee of the order (in quote units)."""
    taker_fee: Decimal
    """Taker fee of the order (in quote units)."""
    api: bool
    """Whether the instrument can be traded via API."""
    details: Any = None
    """Raw details of the rules."""

    def min_qty(self, price: Decimal) -> Decimal:
      """Minimum quantity of the order (in base units)."""
      min_qty = self.min_qty_ or self.step_size
      if self.min_value is not None:
        min_qty = max(min_qty, self.min_value / price)
      return min_qty
    
    def trunc_qty(self, base_qty: Decimal, *, price: Decimal) -> Decimal | None:
      """Truncate the (base asset) quantity to the nearest step size. Returns `None` if the quantity is too small."""
      qty = trunc2tick(base_qty, self.step_size)
      if qty > self.min_qty(price):
        return qty

    def round_price(self, price: Decimal) -> Decimal:
      """Round the price to the nearest tick size."""
      return round2tick(price, self.tick_size)
    
    def amount2qty(self, quote_amount: Decimal, *, price: Decimal) -> Decimal | None:
      """Convert a quote amount to a base quantity, truncating to the nearest step size. Returns `None` if the quantity is too small."""
      return self.trunc_qty(quote_amount / price, price=price)
    
    def qty2amount(self, base_qty: Decimal, *, price: Decimal) -> Decimal:
      """Convert a base quantity to a quote amount."""
      return base_qty * price
  
  @SDK.method
  @abstractmethod
  async def get(self) -> Rules:
    """Fetch market rules."""

  async def __call__(self) -> Rules:
    """Fetch market rules."""
    return await self.get()