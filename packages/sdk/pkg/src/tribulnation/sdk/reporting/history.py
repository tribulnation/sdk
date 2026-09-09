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

    API history is best-effort, not a completeness guarantee. Implementations accept
    either omitted bound and document their endpoint-specific default lookbacks.
    Retention, discovery and endpoint limits may leave gaps for file ingestion.

    Args:
      start: Inclusive lower bound. `None` uses the venue's documented default lookback.
      end: Inclusive upper bound. `None` uses now or the venue's latest available data.
    """
