"""Spot position and collateral, read off the Trading Spot balance list."""

from typing_extensions import TYPE_CHECKING
from decimal import Decimal

from tribulnation.sdk.market import Collateral, Position

if TYPE_CHECKING:
  from .mixin import MarketMixin


async def position(self: 'MarketMixin') -> Position:
  """Fetch the base-asset balance held for this market."""
  balances = await self.shared.load_balances()
  entry = balances.get(self.base)
  if entry is None:
    return Position()
  return Position(
    size=Decimal(str(entry['balance'])) + Decimal(str(entry['blockedBalance']))
  )


async def collateral(self: 'MarketMixin') -> Collateral:
  """Fetch the quote-asset balance backing this market."""
  balances = await self.shared.load_balances()
  entry = balances.get(self.quote)
  if entry is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  free = Decimal(str(entry['balance']))
  blocked = Decimal(str(entry['blockedBalance']))
  return Collateral(equity=free + blocked, free_collateral=free)


async def available_notional(self: 'MarketMixin') -> Decimal:
  """Fetch the free quote-asset balance: what a new order can spend."""
  return (await collateral(self)).free_collateral
