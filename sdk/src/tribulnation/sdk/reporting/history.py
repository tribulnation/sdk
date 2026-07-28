from typing_extensions import AsyncIterable
from datetime import datetime
from abc import abstractmethod

from tribulnation.sdk import SDK
from .models import HistoryRecord

class History(SDK):
  @SDK.method
  @abstractmethod
  def history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[HistoryRecord]:
    """Fetch your reporting history."""

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...
