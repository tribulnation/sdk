from typing_extensions import Protocol
from datetime import datetime

class Time(Protocol):
  async def time(self) -> datetime:
    """Get the current server time."""
    ...