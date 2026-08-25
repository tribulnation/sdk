"""Hyperliquid reporting: history and snapshots."""

from typing_extensions import AsyncContextManager, Collection, Iterable, TypedDict
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import Report as _Report, SnapshotRecord
from typed_hyperliquid.info import Info

from .history import History
from .snapshots import Snapshots


class HyperliquidConfig(TypedDict, total=False):
  """Hyperliquid reporting configuration."""

  cache: str
  """SQLAlchemy URL for the history archive, e.g. `sqlite:///hyperliquid.db`.

  Strongly recommended. Hyperliquid serves only the 10000 most recent fills and
  caps TWAP slices at 2000, so without an archive an account's early history
  becomes permanently unreadable once it passes those limits.
  """
  no_cache: bool
  """Bypass cache reads while still writing. Refreshes the archive; never clears it."""
  mainnet: bool
  """Use mainnet when true, testnet when false. Defaults to true."""


@dataclass(kw_only=True)
class Report(_Report):
  """Combined history and snapshots for one Hyperliquid account."""

  history_impl: History
  snapshots_impl: Snapshots

  @classmethod
  def new(
    cls,
    address: str,
    *,
    config: HyperliquidConfig | None = None,
    validate: bool = True,
  ):
    """Build a report client, sharing one `Info` connection between both surfaces."""
    config = config or {}
    mainnet = config.get('mainnet', True)

    cache = None
    if url := config.get('cache'):
      from .history.cache import HistoryCache

      cache = HistoryCache.connect(url, no_cache_reads=config.get('no_cache', False))

    info = Info.http(validate=validate, mainnet=mainnet)
    return cls(
      history_impl=History(info, address, cache=cache),
      snapshots_impl=Snapshots(info, address),
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    # Both surfaces share one `Info`; only `history_impl` owns it, so it is entered once.
    # Identity de-duplication would not save us here -- it spans a single `resources()`
    # call, not resources nested inside separate owners -- so `Snapshots` must keep
    # declaring none for as long as it is handed a borrowed `Info`.
    yield self.history_impl
    yield self.snapshots_impl

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    """Fetch the account's reporting history."""
    async for record in self.history_impl.history(start, end):
      yield record

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    """Fetch the account's current balances and positions."""
    return await self.snapshots_impl.snapshot(assets)
