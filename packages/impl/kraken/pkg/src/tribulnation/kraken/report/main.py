"""Kraken reporting: history and snapshots over one client."""

from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as _Report

from .history import History
from .snapshots import Snapshots


@dataclass(frozen=True, kw_only=True)
class Report(_Report, History, Snapshots):
  """Combined history and snapshots for one Kraken account.

  Both halves are built on the same `Mixin`, so they share one client field and
  `resources()` enters it once.
  """
