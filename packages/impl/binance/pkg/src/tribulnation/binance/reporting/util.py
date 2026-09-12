"""Helpers shared by the Binance reporting sources."""

from calendar import monthrange
from datetime import datetime
from decimal import Decimal

from tribulnation.sdk.reporting import (
  Fee,
  HistoryRecord,
  Observation,
  source_id,
)

SERVICE = 'binance'


def months_before(time: datetime, months: int) -> datetime:
  """Subtract calendar months, clamping month-end dates to a valid day."""
  year, month = divmod(time.year * 12 + time.month - 1 - months, 12)
  month += 1
  return time.replace(
    year=year, month=month, day=min(time.day, monthrange(year, month)[1])
  )


COMPARTMENTS = {
  'MAIN': 'spot',
  'FUNDING': 'funding',
}
"""Wallet compartment names, keyed by the token Binance uses in `UniversalTransferType`."""


def new_source_id() -> str:
  """Mint the provenance id shared by every record of one sweep."""
  return source_id(SERVICE)


def record(observation: Observation, *, id: str) -> HistoryRecord:
  """Wrap one observation with the sweep's API provenance."""
  return HistoryRecord(
    observations=[observation],
    provenance={'source': 'api', 'service': SERVICE, 'id': id},
  )


def nonzero_fee(amount: Decimal, asset: str) -> Fee | None:
  """Build a `Fee` only when the source charged one."""
  if amount == 0:
    return None
  return Fee(amount=abs(amount), asset=asset)


def split_transfer_type(type: str) -> tuple[str | None, str | None]:
  """Split a `UniversalTransferType` into its source and destination compartments."""
  for token, src in COMPARTMENTS.items():
    prefix = f'{token}_'
    if type.startswith(prefix) and (dst := COMPARTMENTS.get(type[len(prefix) :])):
      return src, dst
  return None, None
