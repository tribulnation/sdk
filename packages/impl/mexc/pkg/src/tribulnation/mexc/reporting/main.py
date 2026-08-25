"""MEXC reporting: snapshots only (history is not yet wired)."""

from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import HistoryRecord, Report as _Report

from .snapshots import Snapshots


@dataclass(frozen=True, kw_only=True)
class Report(_Report, Snapshots):
  """Reporting surface for one MEXC account.

  `snapshot` and `new` are inherited from `Snapshots`; the lifecycle comes from
  `Mixin.resources()` via `Snapshots`, so the HTTP client and the open streams are
  both entered and released.
  """

  def history(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> AsyncIterable[HistoryRecord]:
    raise NotImplementedError('mexc history is not yet wired into ReportSDK.')
