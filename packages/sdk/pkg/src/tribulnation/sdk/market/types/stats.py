from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

@dataclass(kw_only=True)
class PerpStats:
  """A perpetual market's pricing and funding snapshot."""
  index: Decimal
  """Index (oracle) price."""
  mark: Decimal | None = None
  """Mark price, if reported by the venue."""
  funding: Decimal | None = None
  """Predicted funding rate for the next settlement (in relative units, e.g. 0.01 = 1%)."""
  next_funding_time: datetime | None = None
  """Time of the next funding settlement."""
  funding_interval: timedelta | None = None
  """Interval between funding settlements."""
  open_interest: Decimal | None = None
  """Open interest, in base units."""
