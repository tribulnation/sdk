from typing import AsyncIterable
from datetime import datetime
from abc import abstractmethod

from tribulnation.sdk import SDK
from .models import Record

class History(SDK):
  @SDK.method
  @abstractmethod
  def history(self, start: datetime, end: datetime) -> AsyncIterable[Record]:
    """Fetch your reporting history."""

  @SDK.method
  async def __aenter__(self):
    return self

  @SDK.method
  async def __aexit__(self, exc_type, exc_value, traceback):
    ...