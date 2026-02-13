from abc import abstractmethod
from datetime import datetime

from tribulnation.sdk.core import SDK

class Time(SDK):
  @SDK.method
  @abstractmethod
  async def time(self) -> datetime:
    """Get the current server time."""
    ...