from typing_extensions import Literal, Protocol, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(kw_only=True)
class Snapshot:
  asset: str
  time: datetime
  qty: Decimal
  kind: Literal['currency', 'future', 'strategy']
  avg_price: Decimal | None = None
  """Average entry price"""

class Snapshots(Protocol):
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    """Snapshot the portfolio of the account.
    
    - `assets`: hint of assets to snapshot. Behavior depends on the implementation.
      - For platforms that can snapshot all assets, this is ignored.
      - For platforms where all assets can't be known a priori (e.g. a blockchain), only the given `assets` are queried.
    """
    ...