from typing_extensions import Mapping
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

def source_id(service: str) -> str:
  time = datetime.now(timezone.utc).isoformat()
  return f'{service}:{time}:{uuid4()}'


class Balances(defaultdict[str, Decimal]):
  def __init__(self, values: Mapping[str, Decimal] = {}):
    super().__init__(Decimal, values)

  def __add__(self, other: 'Balances | Mapping[str, Decimal]') -> 'Balances':
    other = Balances(other)
    result = Balances()
    for key in set(self) | set(other):
      result[key] = self[key] + other[key]
    return result

  def __repr__(self) -> str:
    return repr(dict(self))
