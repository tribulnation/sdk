from typing_extensions import AsyncIterable
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import HistoryRecord, Report as _Report

from .snapshots import Snapshots


@dataclass(frozen=True, kw_only=True)
class Report(_Report, Snapshots):

  def history(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> AsyncIterable[HistoryRecord]:
    raise NotImplementedError('bit2me history is not yet wired into ReportSDK.')
