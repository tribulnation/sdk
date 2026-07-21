from dataclasses import dataclass
from decimal import Decimal

@dataclass(kw_only=True)
class Ticker:
  """A market's top-of-book and last-trade snapshot.

  Deliberately excludes 24h open/high/low/change: they are derivable from a
  sampled series, and storing them freezes the venue's windowing choices.
  """
  last: Decimal | None = None
  """Last traded price."""
  bid: Decimal | None = None
  """Best bid price."""
  ask: Decimal | None = None
  """Best ask price."""
  bid_qty: Decimal | None = None
  """Quantity available at the best bid, in base units."""
  ask_qty: Decimal | None = None
  """Quantity available at the best ask, in base units."""
  base_volume_24h: Decimal | None = None
  """Traded volume over the last 24h, in base units."""
