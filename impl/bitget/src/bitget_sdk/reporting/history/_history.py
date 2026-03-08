from typing_extensions import AsyncIterable, TypeVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from trading_sdk.reporting import History as _History, Event, Flow

from bitget_sdk.core import SdkMixin
from .spot import SpotHistory
from .futures import FuturesHistory
from .margin import MarginHistory

from .util import TimezoneMixin

@dataclass
class History(TimezoneMixin, SdkMixin, _History):
  """Bitget Reporting History
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """

  def __post_init__(self):
    self.spot_history = SpotHistory(client=self.client, tz=self.tz)
    self.future_history = FuturesHistory(client=self.client, tz=self.tz)
    self.margin_history = MarginHistory(client=self.client, tz=self.tz)

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[_History.History]:
    async for chunk in self.spot_history.history(start, end):
      yield chunk
    async for chunk in self.future_history.history(start, end):
      yield chunk
    async for chunk in self.margin_history.history(start, end):
      yield chunk