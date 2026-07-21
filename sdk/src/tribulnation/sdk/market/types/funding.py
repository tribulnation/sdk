from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

YEAR_SECONDS = Decimal(365 * 24 * 3600)

@dataclass(kw_only=True)
class FundingRate:
  rate: Decimal
  """Funding rate (in relative units, e.g. 0.01 = 1%)."""
  time: datetime
  """Funding payment time."""
  premium: Decimal | None = None
  """Premium (mark vs. index, in relative units), the quantity funding is computed from.

  `None` if the venue does not report it.
  """

@dataclass(kw_only=True)
class NextFunding(FundingRate):
  interval: timedelta

  @property
  def annualized(self) -> Decimal:
    """Annualized funding rate (in relative units, e.g. 0.01 = 1%)."""
    return self.rate * YEAR_SECONDS / Decimal(self.interval.total_seconds())

@dataclass
class FundingPayment:
  amount: Decimal
  """Funding paid (if positive) or received (in quote units)"""
  time: datetime