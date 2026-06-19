from decimal import Decimal
import pydantic

class Position(pydantic.BaseModel):
  size: Decimal
  """Position size (of base units, positive or negative)"""
  avg_price: Decimal
  """Average entry price"""

  @classmethod
  def merge(cls, positions: list['Position']) -> 'Position':
    size = sum(p.size for p in positions)
    if size == 0:
      return cls(size=Decimal(0), avg_price=Decimal(0))
    avg_price = sum(p.size * p.avg_price for p in positions) / size
    return cls(size=size, avg_price=avg_price)

class Snapshot(pydantic.BaseModel):
  time: pydantic.AwareDatetime
  balances: dict[str, Decimal] = {}
  positions: dict[str, Position] = {}