"""Time helpers for dYdX reporting history."""

from datetime import datetime, timezone

from tribulnation.sdk.reporting import Record

def in_window(time: datetime, *, start: datetime | None, end: datetime | None) -> bool:
  """Return whether a timestamp is within an optional reporting window."""
  return (start is None or time >= start) and (end is None or time <= end)

def parse_time(value: datetime | str) -> datetime:
  """Parse an API timestamp into a datetime."""
  if isinstance(value, datetime):
    return value
  return datetime.fromisoformat(value.replace('Z', '+00:00'))

def record_time(record: Record) -> datetime:
  """Return a stable sort key for a reporting record."""
  times = [
    observation.time for observation in record.observations
    if observation.time is not None
  ]
  if record.snapshots:
    times.extend(snapshot.time for snapshot in record.snapshots)
  return min(times) if times else datetime.min.replace(tzinfo=timezone.utc)
