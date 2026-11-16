from dataclasses import dataclass
from decimal import Decimal


@dataclass(kw_only=True)
class Position:
  size: Decimal = Decimal(0)
  """Position size (of base units)"""


@dataclass(kw_only=True)
class PerpPosition(Position):
  entry_price: Decimal = Decimal(0)
  """Position average entry price (in quote units). Only meaningful if size != 0"""


@dataclass(frozen=True, kw_only=True)
class PositionHeadroom:
  """How much more position the venue lets the account open on a market, per direction.

  Notional in quote units, at the venue's mark price: how far a long (or short)
  position may still grow, beyond closing whatever is open in the other direction.
  Closing is never limited. `None` means the venue publishes no limit the SDK reads:
  unknown, treated as unlimited. Free collateral is a separate bound
  (`available_notional`, `Collateral.free_collateral`).
  """

  long: Decimal | None = None
  """Notional the long position may still grow by; `None` without a known limit."""
  short: Decimal | None = None
  """Notional the short position may still grow by; `None` without a known limit."""

  @classmethod
  def capped(
    cls,
    *,
    max_notional: Decimal | None,
    position: Decimal,
    remaining: Decimal | None = None,
  ) -> 'PositionHeadroom':
    """The headroom left under a cap on the position's absolute notional and a cap on new open interest.

    Args:
      max_notional: Cap on `|position|`, in either direction; `None` without one.
      position: Signed notional of the current position, positive long.
      remaining: Notional the market still lets anyone open (an open-interest
        allowance); `None` without one.
    """

    def room(held: Decimal) -> Decimal | None:
      """What is left in one direction, holding `held` of it."""
      own = None if max_notional is None else max_notional - held
      if caps := [c for c in (own, remaining) if c is not None]:
        return max(min(caps), Decimal(0))

    return cls(
      long=room(max(position, Decimal(0))), short=room(max(-position, Decimal(0)))
    )
