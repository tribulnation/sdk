from abc import abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from tribulnation.sdk import SDK

@dataclass
class Position:
  size: Decimal
  """Signed position size (negative for short, positive for long)."""
  entry_price: Decimal | None = None
  """Entry price of the position."""

class MyPosition(SDK):
  @SDK.method
  @abstractmethod
  async def position(self) -> Position | None:
    """Get your open position, if any."""
    ...