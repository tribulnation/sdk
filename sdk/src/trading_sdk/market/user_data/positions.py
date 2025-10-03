from typing_extensions import Protocol, Literal, Sequence
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class Position:
  side: Literal['LONG', 'SHORT']
  size: Decimal
  entry_price: Decimal

class Positions(Protocol):
  async def positions(self, instrument: str, /) -> Sequence[Position]:
    """Get the open position on a given instrument."""
    ...

class PerpPositions(Positions, Protocol):
  async def perp_position(self, base: str, quote: str, /) -> Sequence[Position]:
    """Get the open position on a given perpetual instrument."""
    ...

class InversePerpPositions(Positions, Protocol):
  async def inverse_perp_positions(self, currency: str, /) -> Sequence[Position]:
    """Get the open position on a given inverse perpetual instrument."""
    ...