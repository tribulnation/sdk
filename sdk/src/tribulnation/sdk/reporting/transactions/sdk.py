from typing_extensions import AsyncIterable, Sequence
from abc import abstractmethod
from datetime import datetime

from trading_sdk.core import ChunkedStream, SDK
from .types import Transaction

class Transactions(SDK):
  def transactions(
    self, start: datetime, end: datetime
  ) -> ChunkedStream[Transaction]:
    """Collect all transactions of the account, in a given time range."""
    return ChunkedStream(self._transactions_impl(start=start, end=end))
  
  @SDK.method
  @abstractmethod
  def _transactions_impl(
    self, start: datetime, end: datetime
  ) -> AsyncIterable[Sequence[Transaction]]:
    ...