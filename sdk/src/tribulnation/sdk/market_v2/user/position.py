from abc import abstractmethod
from decimal import Decimal
from dataclasses import dataclass

from tribulnation.sdk.core import SDK
	
class Position(SDK):
  @dataclass
  class Position:
    size: Decimal = Decimal(0)
    """Position size (of base units)"""

  @SDK.method
  @abstractmethod
  async def __call__(self) -> Position:
    """Fetch your (base) balance/position in the market."""


class PerpPosition(Position):
  @dataclass(kw_only=True)
  class Position(Position.Position):
    entry_price: Decimal = Decimal(0)
    """Position average entry price (in quote units). Only meaningful if size != 0"""
    
  @SDK.method
  @abstractmethod
  async def __call__(self) -> Position:
    """Fetch your (base) position in the market."""