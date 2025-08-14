from abc import ABC, abstractmethod
from datetime import datetime

class Time(ABC):
  @abstractmethod
  async def time(self) -> datetime:
    """Get the current server time."""
    ...