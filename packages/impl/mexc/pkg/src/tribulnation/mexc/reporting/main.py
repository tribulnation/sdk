"""MEXC reporting: snapshots and history over one client."""

from typing_extensions import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import HistoryRecord, Report as _Report

from typed_mexc import MEXC

from tribulnation.mexc.core import Settings
from . import history as _history
from .snapshots import Snapshots


@dataclass(frozen=True, kw_only=True)
class Report(_Report, Snapshots):
  """Reporting surface for one MEXC account.

  `snapshot` is inherited from `Snapshots`; the lifecycle comes from
  `Mixin.resources()` via `Snapshots`, so the HTTP client and the open streams are
  both entered and released.
  """

  @classmethod
  def new(
    cls,
    api_key: str | None = None,
    api_secret: str | None = None,
    *,
    settings: Settings = {},
  ):
    """Create a reporting surface over a new MEXC client.

    Args:
      api_key: MEXC API key.
      api_secret: MEXC API secret.
      settings: Client settings (`validate`, `recvWindow`).
    """
    client = MEXC.new(
      api_key=api_key, api_secret=api_secret, validate=settings.get('validate', True)
    )
    return cls(client=client, settings=settings, streams={})

  @SDK.method
  async def history(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> AsyncIterator[HistoryRecord]:
    """Stream the account's reporting history.

    Covers spot fills across the venue's discovered symbols, crypto deposits and withdrawals, and futures
    funding settlements. Not covered, though MEXC exposes the endpoints: futures fills
    and closed positions, spot-futures and sub-account transfers, dust conversions and
    affiliate rebates. Margin has no surface in the typed client at all.

    Args:
      start: Start of the window; omitted means 30 days before `end`.
      end: End of the window. `None` means now.
    """
    async for record in _history.history(self, start, end):
      yield record
