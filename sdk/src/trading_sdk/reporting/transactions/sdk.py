from typing_extensions import Protocol, AsyncIterable, Sequence
from datetime import datetime

from trading_sdk.util import ChunkedStream
from .types import Transaction

class Transactions(Protocol):
  def transactions(
    self, *, start: datetime, end: datetime
  ) -> ChunkedStream[Transaction]:
    """Collect all transactions of the account.
    
    - `start`: if given, collects transactions after this time (inclusive).
    - `end`: if given, collects transactions before this time (inclusive).
    """
    return ChunkedStream(self._transactions_impl(start=start, end=end))
  
  def _transactions_impl(
    self, *, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Transaction]]:
    ...