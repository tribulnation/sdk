from decimal import Decimal
from datetime import datetime
from collections import defaultdict
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

class SubaccountSnapshot(pydantic.BaseModel):
  """Balances and positions scoped to one source-native account compartment."""
  subaccount: str | None = None
  balances: dict[str, Decimal] = pydantic.Field(default_factory=dict)
  positions: dict[str, Position] = pydantic.Field(default_factory=dict)

class Snapshot(pydantic.BaseModel):
  time: pydantic.AwareDatetime = pydantic.Field(default_factory=lambda: datetime.now().astimezone())
  subaccounts: list[SubaccountSnapshot] = pydantic.Field(default_factory=list)

  @pydantic.model_validator(mode='after')
  def unique_subaccounts(self):
    ids = [state.subaccount for state in self.subaccounts]
    if len(ids) != len(set(ids)):
      raise ValueError('Snapshot subaccount identifiers must be unique')
    return self

  @property
  def balances(self) -> dict[str, Decimal]:
    """Return balances aggregated across all subaccounts."""
    balances = defaultdict[str, Decimal](Decimal)
    for subaccount in self.subaccounts:
      for asset, balance in subaccount.balances.items():
        balances[asset] += balance
    return dict(balances)

  @property
  def positions(self) -> dict[str, Position]:
    """Return positions aggregated across all subaccounts."""
    positions = defaultdict[str, list[Position]](list)
    for subaccount in self.subaccounts:
      for instrument, position in subaccount.positions.items():
        positions[instrument].append(position)
    return {
      instrument: Position.merge(parts)
      for instrument, parts in positions.items()
    }
