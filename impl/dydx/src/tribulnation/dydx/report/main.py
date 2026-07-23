from typing_extensions import AsyncIterable, Collection, TypedDict, Literal
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import asyncio

from tribulnation.sdk.reporting import (
  Report as _Report, Record, Snapshot, SnapshotResult, source_id,
  ProvidersConfig
)
from dydx import Dydx
from .history import History
from .snapshots import Snapshots

class DydxConfig(TypedDict, total=False):
  require_bigquery: bool
  block_time_cache_path: Path | str
  archive_node: Literal['kingnodes', 'polkachu']

@dataclass(kw_only=True)
class Report(_Report):
  history_impl: History
  snapshots_impl: Snapshots

  @classmethod
  def new(
    cls, address: str, *,
    config: DydxConfig | None = None,
    providers: ProvidersConfig | None = None,
  ):
    config = config or {}
    providers = providers or {}
    require_bigquery = config.get('require_bigquery', False)
    if (block_time_cache_path := config.get('block_time_cache_path')):
      from .history.block_time import FilesBlockTimeCache
      block_time_cache = FilesBlockTimeCache.at(block_time_cache_path)
    else:
      block_time_cache = None
    if (bigquery := providers.get('bigquery')):
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
      history_impl=History.of(address, dydx=dydx, bigquery=bigquery, block_time_cache=block_time_cache, require_bigquery=require_bigquery),
      snapshots_impl=Snapshots.of(address),
    )

  async def __aenter__(self):
    await asyncio.gather(
      self.history_impl.__aenter__(),
      self.snapshots_impl.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      self.history_impl.__aexit__(exc_type, exc_value, traceback),
      self.snapshots_impl.__aexit__(exc_type, exc_value, traceback),
    )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    async for record in self.history_impl.history(start, end):
      yield record

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotResult:
    return await self.snapshots_impl.snapshot(assets)

  async def records(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
      start_time: datetime | None = None
      async for record in self.history(start, end):
        yield record
        for obs in record.observations:
          if obs.time is not None:
            start_time = obs.time if start_time is None else min(start_time, obs.time)

      if start is None and start_time is not None:
        start_time = start_time.astimezone()
        snapshot_time = start_time - timedelta(days=1)
        yield Record(
          snapshots=[Snapshot(time=snapshot_time)],
          provenance={
            'source': 'derived',
            'id': source_id('dydx'),
            'details': {
              'note': 'dYdX full-history reports imply zero balances before the first observed transaction.',
            }
          },
        )

      if end is None:
        result = await self.snapshot()
        yield Record(snapshots=[result.snapshot], provenance=result.provenance)
