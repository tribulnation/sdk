from typing_extensions import AsyncIterable
from datetime import datetime
from abc import abstractmethod

from tribulnation.sdk import SDK
from .models import HistoryRecord


class History(SDK):
  @SDK.method
  @abstractmethod
  def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[HistoryRecord]:
    """Stream your transaction history as `HistoryRecord`s, each with its `Provenance`.

    Args:
      start: Start of the window (inclusive). `None` starts from the earliest available.
      end: End of the window (inclusive). `None` means everything since `start`.
    """
