"""Helpers shared by the Binance reporting sources."""

from typing_extensions import Sequence
from decimal import Decimal

from tribulnation.sdk.core import AuthError
from tribulnation.sdk.reporting import (
  Fee,
  HistoryRecord,
  Observation,
  source_id,
)

SERVICE = 'binance'

COMPARTMENTS = {
  'MAIN': 'spot',
  'FUNDING': 'funding',
  'UMFUTURE': 'usdm_futures',
  'CMFUTURE': 'coinm_futures',
  'MARGIN': 'cross_margin',
  'ISOLATEDMARGIN': 'isolated_margin',
  'OPTION': 'options',
  'PORTFOLIO_MARGIN': 'portfolio_margin',
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


def raise_if_all_failed(failures: Sequence[AuthError], sources: int):
  """Re-raise when every source hit the same credential wall.

  An `AuthError` from one source is a real per-surface permission gap (Binance gates
  futures, margin and options behind separate API-key flags), so the rest of the sweep
  still stands. An `AuthError` from all of them is a broken key, not a capability gap.
  """
  if failures and len(failures) == sources:
    raise failures[0]
