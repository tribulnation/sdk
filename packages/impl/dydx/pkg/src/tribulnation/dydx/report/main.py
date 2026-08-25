import asyncio
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from tribulnation.dydx.core import USDC
from tribulnation.sdk.reporting import (
  ProvidersConfig,
  Snapshot,
  SnapshotRecord,
  SubaccountSnapshot,
)
from tribulnation.sdk.reporting import Report as _Report
from typing_extensions import AsyncContextManager, TypedDict

from typed_dydx import Dydx

from .history import History
from .history.indexer import ReplayPosition, replay_fills
from .snapshots import Snapshots


class DydxConfig(TypedDict, total=False):
  require_bigquery: bool
  archive_node: Literal['kingnodes', 'polkachu']
  cache: str
  no_cache: bool


def normalize_perpetual_collateral(
  snapshot: Snapshot,
  replayed: dict[str, dict[str, ReplayPosition]],
) -> Snapshot:
  """Express dYdX collateral using the fill replay's average-cost basis."""
  subaccounts: list[SubaccountSnapshot] = []
  for state in snapshot.subaccounts:
    positions = replayed.get(state.subaccount or '')
    if positions is None:
      subaccounts.append(state)
      continue
    reported_basis = sum(
      (position.size * position.avg_price for position in state.positions.values()),
      start=Decimal(0),
    )
    replayed_basis = sum(
      (
        position.signed_size * (position.entry_price or Decimal(0))
        for position in positions.values()
      ),
      start=Decimal(0),
    )
    balances = dict(state.balances)
    balances[USDC] = balances.get(USDC, Decimal(0)) + replayed_basis - reported_basis
    subaccounts.append(state.model_copy(update={'balances': balances}))
  return snapshot.model_copy(update={'subaccounts': subaccounts})


@dataclass(kw_only=True)
class Report(_Report):
  history_impl: History
  snapshots_impl: Snapshots

  @classmethod
  def new(
    cls,
    address: str,
    *,
    config: DydxConfig | None = None,
    providers: ProvidersConfig | None = None,
  ):
    config = config or {}
    providers = providers or {}
    require_bigquery = config.get('require_bigquery', False)

    cache = None
    if cache_url := config.get('cache'):
      from .history.cache import HistoryCache

      no_cache = config.get('no_cache', False)
      cache = HistoryCache.connect(cache_url, no_cache_reads=no_cache)

    if bigquery := providers.get('bigquery'):
      from .history.bigquery import bigquery_client

      bigquery = bigquery_client(providers)

    archive_node = config.get('archive_node')
    if archive_node == 'kingnodes':
      dydx = Dydx.kingnodes_archive(public=True)
    elif archive_node == 'polkachu':
      dydx = Dydx.polkachu_archive(public=True)
    else:
      dydx = None

    return cls(
      history_impl=History.of(
        address,
        dydx=dydx,
        bigquery=bigquery,
        cache=cache,
        require_bigquery=require_bigquery,
      ),
      snapshots_impl=Snapshots.of(address),
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    # Sequential, not gathered: a gather that fails on the second entry orphans the first
    # forever. Entering a client is local work, so ordered rollback is worth the wait.
    yield self.history_impl
    yield self.snapshots_impl

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    async for record in self.history_impl.history(start, end):
      yield record

  async def snapshot_fills(self, subaccount: int, *, end: datetime):
    """Use the just-ingested genesis cache when it is current enough."""
    indexer = self.history_impl.indexer
    cache = indexer.cache
    if cache is not None:
      coverage = cache.indexer_fill_coverage(indexer.address, subaccount)
      if coverage is not None and end - coverage <= timedelta(minutes=2):
        return cache.read_indexer_fills(indexer.address, subaccount, end=end)
    return await indexer.fetch_fills(subaccount=subaccount, end=end)

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    record = await self.snapshots_impl.snapshot(assets)
    perpetuals = [
      state
      for state in record.snapshot.subaccounts
      if state.subaccount is not None and state.subaccount != 'chain'
    ]
    fill_streams = await asyncio.gather(
      *[
        self.snapshot_fills(
          subaccount=int(subaccount),
          end=record.snapshot.time,
        )
        for state in perpetuals
        if (subaccount := state.subaccount) is not None
      ]
    )
    replayed = {
      state.subaccount: replay_fills(fills)[1]
      for state, fills in zip(perpetuals, fill_streams)
      if state.subaccount is not None
    }
    snapshot = normalize_perpetual_collateral(record.snapshot, replayed)
    return record.model_copy(update={'snapshot': snapshot})
