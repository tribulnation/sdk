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