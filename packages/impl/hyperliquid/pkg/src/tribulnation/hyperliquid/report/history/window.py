"""Time-window helpers for Hyperliquid reporting history."""

from datetime import datetime, timezone


def in_window(
  time: datetime | None,
  *,
  start: datetime | None,
  end: datetime | None,
) -> bool:
  """Return whether a timestamp belongs to an inclusive history window."""
  if time is None:
    return True
  return (start is None or time >= start) and (end is None or time <= end)


def parse_time(value: datetime | int) -> datetime:
  """Convert a Hyperliquid millisecond timestamp to an aware datetime.

  Observation times are `pydantic.AwareDatetime`, so the result must carry a
  timezone. Hyperliquid timestamps are UTC.
  """
  if isinstance(value, datetime):
    return value
  return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def dump_time(time: datetime | None, *, default: int) -> int:
  """Convert a datetime to a Hyperliquid millisecond timestamp."""
  if time is None:
    return default
  return int(time.timestamp() * 1000)
