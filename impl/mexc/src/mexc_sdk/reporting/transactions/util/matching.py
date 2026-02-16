from typing_extensions import Iterable, Protocol
from datetime import timezone

from trading_sdk.reporting.transactions import Event

class Module(Protocol):
  @staticmethod
  def parse(path: str, tz: timezone, /, *, skip_zero_changes: bool = True) -> Iterable[Event]:
    ...
