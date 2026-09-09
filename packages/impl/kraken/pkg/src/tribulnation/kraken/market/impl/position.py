"""Spot position and collateral, read off the extended balance list."""

from typing_extensions import TYPE_CHECKING
from decimal import Decimal

from tribulnation.sdk.market import Collateral, Position

if TYPE_CHECKING:
  from .mixin import MarketMixin


async def position(self: 'MarketMixin') -> Position:
  """Fetch the base-asset balance held for this market, held amounts included."""
  balances = await self.shared.load_balances()
  entry = balances.get(self.base)
  if entry is None:
    return Position()
  return Position(size=entry.get('balance', Decimal(0)))


async def collateral(self: 'MarketMixin') -> Collateral:
  """Fetch the quote-asset balance backing this market.

  `hold_trade` is what resting spot orders have reserved; the rest is free.
  """
  balances = await self.shared.load_balances()
  entry = balances.get(self.quote)
  if entry is None:
    return Collateral(equity=Decimal(0), free_collateral=Decimal(0))
  balance = entry.get('balance', Decimal(0))
  return Collateral(
    equity=balance, free_collateral=balance - entry.get('hold_trade', Decimal(0))
  )


async def available_notional(self: 'MarketMixin') -> Decimal:
  """Fetch the free quote-asset balance: what a new order can spend."""
  return (await collateral(self)).free_collateral
