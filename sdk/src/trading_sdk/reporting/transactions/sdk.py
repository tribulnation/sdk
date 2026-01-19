from typing_extensions import Protocol, AsyncIterable, Sequence
from datetime import datetime

from trading_sdk.util import ChunkedStream
from .types import Transaction

class Transactions(Protocol):
  def transactions(
    self, start: datetime, end: datetime
  ) -> ChunkedStream[Transaction]:
    """Collect all transactions of the account, in a given time range."""
    return ChunkedStream(self._transactions_impl(start=start, end=end))
  
  def _transactions_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Transaction]]:
    ...