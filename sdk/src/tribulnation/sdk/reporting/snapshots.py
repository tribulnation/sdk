from typing_extensions import Literal
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk import SDK

@dataclass(kw_only=True)
class Balance:
  qty: Decimal
  kind: Literal['currency', 'future', 'strategy']
  avg_price: Decimal | None = None
  """Average entry price"""


@dataclass(kw_only=True)
class Snapshot:
  time: datetime
  balances: dict[str, Balance]


class Snapshots(SDK):
  @SDK.method
  @abstractmethod
  async def snapshots(self) -> Snapshot:
    """Snapshot the full portfolio of the account."""
    ...

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...
