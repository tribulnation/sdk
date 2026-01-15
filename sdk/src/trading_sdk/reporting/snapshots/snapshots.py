from typing_extensions import Literal, Protocol, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(kw_only=True)
class BaseSnapshot:
  asset: str
  time: datetime
  qty: Decimal

@dataclass(kw_only=True)
class CurrencySnapshot(BaseSnapshot):
  kind: Literal['currency'] = 'currency'

@dataclass(kw_only=True)
class FutureSnapshot(BaseSnapshot):
  kind: Literal['future'] = 'future'
  avg_price: Decimal
  """Average entry price"""

@dataclass(kw_only=True)
class StrategySnapshot(BaseSnapshot):
  kind: Literal['strategy'] = 'strategy'

Snapshot = CurrencySnapshot | FutureSnapshot | StrategySnapshot

class Snapshots(Protocol):
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    """Snapshot the portfolio of the account.
    
    - `assets`: hint of assets to snapshot. Behavior depends on the implementation.
      - For platforms that can snapshot all assets, this is ignored.
      - For platforms where all assets can't be known a priori (e.g. a blockchain), only the given `assets` are queried.
    """
    ...