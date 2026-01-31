from dataclasses import dataclass, field
from datetime import datetime

def ensure_datetime(x) -> datetime:
  return x if isinstance(x, datetime) else datetime.fromisoformat(str(x))


@dataclass
class UniqueIds:
  used: set[str] = field(default_factory=set)

  def new(self, prefix: str) -> str:
    if prefix in self.used:
      i = 1
      while (id := f'{prefix};{i}') in self.used:
        i += 1
    else:
      id = prefix
    self.used.add(id)
    return id