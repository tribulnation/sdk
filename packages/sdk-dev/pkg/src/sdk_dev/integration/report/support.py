"""Support for report integration tests."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import HistoryRecord, SnapshotRecord


@dataclass(frozen=True, kw_only=True)
class ReportResult:
  """Results of reading one account's snapshot and history."""

  venue: str
  """The account's venue id, so venue-specific cases can pick their accounts."""
  start: datetime
  """Lower bound of the history window that was asked for."""
  end: datetime
  """Upper bound of the history window that was asked for."""
  snapshot: SnapshotRecord | None = None
  snapshot_failure: str | None = None
  records: Sequence[HistoryRecord] | None = None
  history_failure: str | None = None
