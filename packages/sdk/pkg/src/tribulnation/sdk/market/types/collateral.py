from dataclasses import dataclass
from decimal import Decimal
from typing_extensions import Literal


@dataclass(kw_only=True)
class Collateral:
  """The money behind a collateral ID: a spot asset balance or a margin pool."""

  equity: Decimal
  """Total value, in the collateral's own units: the asset for a spot ID, the pool's
  settlement asset for a margin pool."""
  free_collateral: Decimal
  """What new orders can still use: not held by open orders or margin. Opening
  capacity, NOT risk."""


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


@dataclass(kw_only=True)
class Balance:
  """One spot asset's balance, in that asset's units."""

  total: Decimal
  """Everything held, including what open orders hold."""
  free: Decimal
  """What new orders can use: `total` less what open orders hold."""


@dataclass(kw_only=True)
class SpotBalances:
  """The balances of a spot pair's two assets."""

  base: Balance
  """The base asset: what a sell spends."""
  quote: Balance
  """The quote asset: what a buy spends."""


@dataclass(frozen=True, kw_only=True)
class SpotCollateralIds:
  """The collateral IDs a spot pair's orders reserve on."""

  base: str
  """`<account_id>:<exchange_id>:<base asset>`: what a sell reserves on."""
  quote: str
  """`<account_id>:<exchange_id>:<quote asset>`: what a buy reserves on."""
