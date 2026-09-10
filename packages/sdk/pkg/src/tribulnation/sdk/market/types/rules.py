from typing_extensions import Any
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk.util import ceil2tick, trunc2tick, round2tick
from .fees import Fees


@dataclass(kw_only=True)
class Rules:
  """Trading constraints; base and quote identities belong to the Catalogue."""
  fee_asset: str
  """Asset used for fees/funding payments."""
  tick_size: Decimal
  """Tick size of the price (in quote units)."""
  step_size: Decimal
  """Step size of the quantity (in base units)."""
  fixed_min_qty: Decimal | None = None
  """Minimum quantity of the order (in base units)."""
  min_value: Decimal | None = None
  """Minimum value of the order (in quote units)."""
  max_qty: Decimal | None = None
  """Maximum quantity of the order (in base units)."""
  fixed_min_price: Decimal | None = None
  """Minimum price of the order (in quote units)."""
  rel_min_price: Decimal | None = None
  """Minimum price of the order (in quote units), relative to the current price (e.g. 0.95 = 5% below the current price)."""
  rel_max_price: Decimal | None = None
  """Maximum price of the order (in quote units), relative to the current price (e.g. 1.05 = 5% above the current price)."""
  fixed_max_price: Decimal | None = None
  """Maximum price of the order (in quote units)."""
  fees: Fees | None = None
  """Combined standard non-VIP API rates, or an unknown schedule.

  Never account-specific; excludes optional fee-payment discounts.
  Use `Market.fees()` for the configured account's combined rates.
  """
  api: bool
  """Whether the instrument can be traded via API."""
  details: Any = None
  """Raw details of the rules."""

  def min_price(self, mark_price: Decimal, /) -> Decimal | None:
    """Minimum price of the order (in quote units), accounting for the minimum value and fixed minimum price."""
    values: list[Decimal] = []
    if self.fixed_min_price is not None:
      values.append(self.fixed_min_price)
    if self.rel_min_price is not None:
      values.append(self.rel_min_price * mark_price)
    return min(values, default=None)

  def max_price(self, mark_price: Decimal, /) -> Decimal | None:
    """Maximum price of the order (in quote units), accounting for the maximum value and fixed maximum price."""
    values: list[Decimal] = []
    if self.fixed_max_price is not None:
      values.append(self.fixed_max_price)
    if self.rel_max_price is not None:
      values.append(self.rel_max_price * mark_price)
    return max(values, default=None)

  def min_qty(self, price: Decimal) -> Decimal:
    """Minimum quantity of the order (in base units), accounting for the minimum value and fixed minimum quantity."""
    min_qty = self.fixed_min_qty or self.step_size
    if self.min_value is not None:
      min_qty = max(min_qty, self.min_value / price)
    return ceil2tick(min_qty, self.step_size)

  def trunc_qty(self, base_qty: Decimal, *, price: Decimal) -> Decimal | None:
    """Truncate the (base asset) quantity to the nearest step size. Returns `None` if the quantity is too small."""
    qty = trunc2tick(base_qty, self.step_size)
    if qty > self.min_qty(price):
      return qty

  def round_qty(self, base_qty: Decimal, *, price: Decimal) -> Decimal | None:
    """Round the (base asset) quantity to the nearest step size."""
    qty = round2tick(base_qty, self.step_size)
    if qty > self.min_qty(price):
      return qty

  def round_price(self, price: Decimal) -> Decimal:
    """Round the price to the nearest tick size."""
    return round2tick(price, self.tick_size)

  def trunc_price(self, price: Decimal) -> Decimal:
    """Truncate the price to the nearest tick size."""
    return trunc2tick(price, self.tick_size)

  def ceil_price(self, price: Decimal) -> Decimal:
    """Ceil the price to the nearest tick size."""
    return ceil2tick(price, self.tick_size)

  def notional2qty(self, notional: Decimal, *, price: Decimal) -> Decimal | None:
    """Convert a notional value (in quote units) to a base quantity, truncating to the nearest step size. Returns `None` if the quantity is too small."""
    return self.trunc_qty(notional / price, price=price)

  def qty2notional(self, base_qty: Decimal, *, price: Decimal) -> Decimal:
    """Convert a base quantity to its notional value, in quote units."""
    return base_qty * price
