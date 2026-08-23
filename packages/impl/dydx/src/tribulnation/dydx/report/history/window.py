"""Time-window helpers for dYdX reporting history."""

from datetime import datetime

def in_window(
  time: datetime | None, *, start: datetime | None, end: datetime | None,
) -> bool:
  """Return whether a timestamp belongs to an inclusive history window."""
  if time is None:
    return True
  return (start is None or time >= start) and (end is None or time <= end)
