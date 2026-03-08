from typing_extensions import TypeVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from trading_sdk.reporting.history import Flow, Event

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

Tx = TypeVar('Tx', Flow, Event)

@dataclass(kw_only=True)
class TimezoneMixin:
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz

  def add_tz(self, time: datetime) -> datetime:
    return time.replace(tzinfo=self.timezone)