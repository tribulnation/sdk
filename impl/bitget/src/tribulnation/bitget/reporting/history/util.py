from typing_extensions import Any, Literal
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from tribulnation.sdk.reporting import (
  ApiProvenance,
  Fee,
  Observation,
  Record,
)

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

@dataclass(kw_only=True)
class TimezoneMixin:
  """Adds a configured timezone to Bitget timestamp values."""
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

def api_provenance(endpoint: str, response: Any) -> ApiProvenance:
  """Build Bitget API provenance for a raw source response."""
  return {
    'source': 'api',
    'service': 'bitget',
    'endpoint': endpoint,
    'response': response,
  }

def api_record(observation: Observation, *, endpoint: str, response: Any) -> Record:
  """Wrap one Bitget observation with its API provenance."""
  return Record(observations=[observation], provenance=api_provenance(endpoint, response))

def api_record_many(observations: list[Observation], *, endpoint: str, response: Any) -> Record:
  """Wrap related Bitget observations from a single source row."""
  return Record(observations=observations, provenance=api_provenance(endpoint, response))

def signed_size(size: Decimal, side: Literal['buy', 'sell']) -> Decimal:
  """Convert a buy/sell side into a signed trade size."""
  return size if side == 'buy' else -size

def nonzero_fee(amount: Decimal, asset: str) -> Fee | None:
  """Return a fee object only when the source amount is nonzero."""
  fee = abs(amount)
  if fee == 0:
    return None
  return Fee(amount=fee, asset=asset)

def require_range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
  """Require the explicit time range Bitget history endpoints need."""
  if start is None or end is None:
    raise ValueError('Bitget history requires both start and end.')
  return start, end
