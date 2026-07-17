from dataclasses import dataclass
from decimal import Decimal
from typing_extensions import Literal

@dataclass(kw_only=True)
class Collateral:
  """Spot / base collateral of an account bucket."""
  equity: Decimal
  """Total account value in quote units (spot: total quote balance)."""
  free_collateral: Decimal
  """Collateral not backing positions/orders (withdrawable). Opening capacity, NOT risk."""

@dataclass(kw_only=True)
class PerpCollateral(Collateral):
  """Perpetual collateral of an account bucket."""
  initial_margin: Decimal
  """Quote units. Can't open new positions when equity <= initial_margin."""
  maintenance_margin: Decimal
  """Quote units. Liquidation when equity <= maintenance_margin."""
  leverage: Decimal
  """Total position notional / equity. 0 when flat."""
  margin_mode: Literal['cross', 'isolated']
  """Which bucket this is. Always known."""

  @property
  def initial_ratio(self) -> Decimal:
    """initial_margin / equity. Can't open more at >= 1. +Infinity when equity <= 0."""
    if self.equity <= 0:
      return Decimal('Infinity')
    return self.initial_margin / self.equity

  @property
  def maintenance_ratio(self) -> Decimal:
    """maintenance_margin / equity. Liquidation at >= 1. +Infinity when equity <= 0."""
    if self.equity <= 0:
      return Decimal('Infinity')
    return self.maintenance_margin / self.equity
