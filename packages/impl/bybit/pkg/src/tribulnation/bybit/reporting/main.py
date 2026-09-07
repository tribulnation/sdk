"""Bybit reporting: snapshots and history over one client."""

from typing_extensions import AsyncIterator, Collection
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import (
  HistoryRecord,
  Report as _Report,
  SnapshotRecord,
)

from tribulnation.bybit.core import Mixin
from . import history as _history
from . import snapshots as _snapshots


@dataclass(kw_only=True, frozen=True)
class Report(Mixin, _Report):
  """Combined history and snapshots for one Bybit account.

  Both surfaces read the same unified account off the same client, so they are one
  object here rather than two sharing a borrowed connection.
  """

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's current balances and positions."""
    return await _snapshots.snapshot(self, assets)

  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterator[HistoryRecord]:
    """Stream the account's reporting history.

    Covers spot fills, linear funding settlements, and crypto deposits and
    withdrawals. Not covered, though Bybit exposes the endpoints: derivatives fills
    and closed PnL, internal UID-to-UID transfers, Earn subscribe/redeem events,
    bonus and airdrop credits, and fiat on/off-ramp.

    Args:
      start: Start of the window. `None` starts two years back, Bybit's retention limit.
      end: End of the window. `None` means now.
    """
    async for record in _history.history(self, start, end):
      yield record
