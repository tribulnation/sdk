"""Coinbase reporting: history and snapshots over one client."""

from dataclasses import dataclass

from tribulnation.sdk.reporting import Report as _Report

from .history import History
from .snapshots import Snapshots


@dataclass(frozen=True, kw_only=True)
class Report(_Report, History, Snapshots):
  """Reporting for one Coinbase account.

  Both surfaces borrow the same `Shared`, so the client is entered once however many
  of them a caller holds.
  """
