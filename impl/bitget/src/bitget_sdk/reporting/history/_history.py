from typing_extensions import AsyncIterable, TypeVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from trading_sdk.reporting import History as _History, Event, Flow

from bitget_sdk.core import SdkMixin
from .spot import SpotHistory
from .futures import FuturesHistory
from .margin import MarginHistory

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

Tx = TypeVar('Tx', Flow, Event)

@dataclass
class History(SdkMixin, _History):
  """Bitget Reporting History
  
  **Does not support**:
  - P2P trading
  - Copy trading
  """
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz

  def add_tz(self, tx: Tx) -> Tx:
    return replace(tx, time=tx.time.replace(tzinfo=self.timezone))

  def __post_init__(self):
    self.spot_history = SpotHistory(self.client)
    self.future_history = FuturesHistory(self.client)
    self.margin_history = MarginHistory(self.client)

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[_History.History]:
    async for chunk in self.spot_history.history(start, end):
      yield chunk
    async for chunk in self.future_history.history(start, end):
      yield chunk
    async for chunk in self.margin_history.history(start, end):
      yield chunk