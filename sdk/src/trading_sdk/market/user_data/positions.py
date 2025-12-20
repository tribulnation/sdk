from typing_extensions import Protocol
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class Position:
  size: Decimal
  """Signed position size (negative for short, positive for long)."""
  entry_price: Decimal

class MyPosition(Protocol):
  async def position(self) -> Position | None:
    """Get your open position, if any."""
    ...