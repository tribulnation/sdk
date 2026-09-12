"""Shared conversion and paging for legacy Classic report history."""

from typing_extensions import Any, AsyncIterator, Awaitable, Callable, Literal, TypeVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  Fee,
  Observation,
  HistoryRecord,
)


class AutoDetect:
  """Use the local timezone only for legacy naive timestamps."""


AUTO_DETECT = AutoDetect()


@dataclass(kw_only=True)
class TimezoneMixin:
  """Adds a configured timezone to Bitget timestamp values."""

  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @property
  def timezone(self) -> timezone:
    """Resolve the legacy timestamp timezone."""
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo  # type: ignore
    else:
      return self.tz

  def add_tz(self, time: datetime) -> datetime:
    """Keep aware Typed timestamps intact; localize only legacy naive values."""
    return time if time.tzinfo is not None else time.replace(tzinfo=self.timezone)


Row = TypeVar('Row')


async def id_pages(
  fetch: Callable[[str | None], Awaitable[list[Row]]],
  key: Callable[[Row], str],
) -> AsyncIterator[list[Row]]:
  """Walk a Classic ID cursor until empty or no new rows, without replaying rows."""
  cursor: str | None = None
  seen: set[str] = set()
  while rows := await fetch(cursor):
    fresh: list[Row] = []
    for row in rows:
      if (identity := key(row)) not in seen:
        seen.add(identity)
        fresh.append(row)
    if not fresh:
      return
    yield fresh
    cursor = key(rows[-1])


def windows(start: datetime, end: datetime):
  """Split legacy inclusive history bounds into at most 30-day wire windows."""
  while start <= end:
    upper = min(start + timedelta(days=30) - timedelta(milliseconds=1), end)
    yield start, upper
    start = upper + timedelta(milliseconds=1)


def api_provenance(endpoint: str, response: Any) -> ApiProvenance:
  """Build Bitget API provenance for a raw source response."""
  return {'source': 'api', 'service': 'bitget', 'id': ''}


def api_record(
  observation: Observation, *, endpoint: str, response: Any
) -> HistoryRecord:
  """Wrap one Bitget observation with its API provenance."""
  return HistoryRecord(
    observations=[observation], provenance=api_provenance(endpoint, response)
  )


def api_record_many(
  observations: list[Observation], *, endpoint: str, response: Any
) -> HistoryRecord:
  """Wrap related Bitget observations from a single source row."""
  return HistoryRecord(
    observations=observations, provenance=api_provenance(endpoint, response)
  )


def signed_size(size: Decimal, side: Literal['buy', 'sell']) -> Decimal:
  """Convert a buy/sell side into a signed trade size."""
  return size if side == 'buy' else -size


def nonzero_fee(amount: Decimal, asset: str) -> Fee | None:
  """Return a fee object only when the source amount is nonzero."""
  fee = abs(amount)
  if fee == 0:
    return None
  return Fee(amount=fee, asset=asset)


def require_range(
  start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
  """Resolve optional history bounds to a recent best-effort 30-day window."""
  end = end if end is not None else datetime.now(timezone.utc)
  start = start if start is not None else end - timedelta(days=30)
  if start.utcoffset() is None or end.utcoffset() is None:
    raise ValueError('Bitget history bounds must be timezone-aware.')
  if start > end:
    raise ValueError('Bitget history start must not follow end.')
  return start, end
