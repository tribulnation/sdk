"""Support for report snapshot integration tests."""

from dataclasses import dataclass

from tribulnation.sdk.reporting import SnapshotRecord


@dataclass(frozen=True, kw_only=True)
class ReportResult:
  """Result of reading one account's current snapshot."""

  snapshot: SnapshotRecord | None = None
  snapshot_failure: str | None = None
