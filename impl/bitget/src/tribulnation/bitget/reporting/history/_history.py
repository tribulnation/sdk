from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import History as SdkHistory, Record

from tribulnation.bitget.core import SdkMixin
from .spot import SpotHistory
from .futures import FuturesHistory
from .margin import MarginHistory

from .util import TimezoneMixin, require_range

@dataclass
class History(TimezoneMixin, SdkMixin, SdkHistory):
  """Bitget Reporting History
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """

  def __post_init__(self):
    """Create product-specific Bitget history fetchers."""
    self.spot_history = SpotHistory(client=self.client, tz=self.tz)
    self.future_history = FuturesHistory(client=self.client, tz=self.tz)
    self.margin_history = MarginHistory(client=self.client, tz=self.tz)

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterable[Record]:
    """Fetch all supported Bitget reporting records."""
    start, end = require_range(start, end)
    async for chunk in self.spot_history.history(start, end):
      yield chunk
    async for chunk in self.future_history.history(start, end):
      yield chunk
    async for chunk in self.margin_history.history(start, end):
      yield chunk
