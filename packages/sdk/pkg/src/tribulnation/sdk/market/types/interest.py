"""Borrow interest charged on margin debt."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(kw_only=True)
class InterestPayment:
  """One borrow-interest charge: the carry of a margin position, as funding is a
  perpetual's.

  A charge is on a borrowed asset, not on a market, and is reported by one market only.
  Where the venue adds interest to the debt, `MarginMarket.position()` includes it
  already: add charges to fill-based P&L, not to a mark-to-market of the position.
  """

  time: datetime
  """When the venue charged it."""
  asset: str
  """Venue-native asset ID the interest is denominated in (the borrowed asset), in the
  form `SpotRules.base` uses, e.g. `'LIT'`."""
  amount: Decimal
  """Signed amount in units of `asset`: negative when paid, positive when received."""
