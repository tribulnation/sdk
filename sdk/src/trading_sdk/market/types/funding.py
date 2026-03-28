from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass(kw_only=True)
class FundingRate:
  rate: Decimal
  """Funding rate (in relative units, e.g. 0.01 = 1%)."""
  time: datetime
  """Funding payment time."""

@dataclass
class FundingPayment:
  amount: Decimal
  """Funding paid (if positive) or received (in quote units)"""
  time: datetime