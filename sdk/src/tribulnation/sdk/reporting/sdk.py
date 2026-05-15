from typing_extensions import AsyncIterable
from datetime import datetime

from tribulnation.sdk import SDK
from .snapshots import Snapshots
from .history import History
from .models import Record

class Report(History, Snapshots):
  @SDK.method
  async def records(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch reporting records, including a current snapshot for open-ended requests."""
    async for record in self.history(start, end):
      yield record
    if end is None:
      yield await self.snapshots()
