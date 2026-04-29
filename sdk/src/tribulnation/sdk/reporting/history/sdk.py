from typing import AsyncIterable
from datetime import datetime
from abc import abstractmethod

from tribulnation.sdk import SDK
from .models import History

class HistoryAPI(SDK):
  @SDK.method
  @abstractmethod
  def history(self, start: datetime, end: datetime) -> AsyncIterable[History]:
    """Fetch your reporting history."""