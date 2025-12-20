from typing_extensions import Protocol, AsyncIterable, Sequence, Mapping
from datetime import datetime

from .types import Transaction, Snapshot

class Transactions(Protocol):
  def transactions(
    self, *, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Transaction]]:
    """Collect all transactions of the account.
    
    - `start`: if given, collects transactions after this time (inclusive).
    - `end`: if given, collects transactions before this time (inclusive).
    """
    ...

  async def transactions_sync(
    self, *, start: datetime, end: datetime
  ) -> Sequence[Transaction]:
    """Collect all transactions of the account.
    
    - `start`: if given, collects transactions after this time (inclusive).
    - `end`: if given, collects transactions before this time (inclusive).
    """
    return [tx async for chunk in self.transactions(start=start, end=end) for tx in chunk]
  
class Snapshots(Protocol):
  async def snapshots(self, assets: Sequence[str] = []) -> Sequence[Snapshot]:
    """Snapshot the portfolio of the account.
    
    - `assets`: hint of assets to snapshot. Behavior depends on the implementation.
      - For platforms that can snapshot all assets, this is ignored.
      - For platforms where all assets can't be known a priori (e.g. a blockchain), only the given `assets` are queried.
    """
    ...

class Report(Transactions, Snapshots):
  ...