from typing_extensions import Collection, TypedDict, Literal
from dataclasses import dataclass
from datetime import datetime
import asyncio

from tribulnation.sdk.reporting import (
  Report as _Report, SnapshotRecord,
  ProvidersConfig
)
from dydx import Dydx
from .history import History
from .snapshots import Snapshots

class DydxConfig(TypedDict, total=False):
  require_bigquery: bool
  archive_node: Literal['kingnodes', 'polkachu']
  cache: str
  no_cache: bool

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

    cache = None
    if (cache_url := config.get('cache')):
      from .history.cache import HistoryCache
      no_cache = config.get('no_cache', False)
      cache = HistoryCache.connect(cache_url, no_cache_reads=no_cache)

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
      history_impl=History.of(
        address, dydx=dydx, bigquery=bigquery,
        cache=cache, require_bigquery=require_bigquery,
      ),
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

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    return await self.snapshots_impl.snapshot(assets)
