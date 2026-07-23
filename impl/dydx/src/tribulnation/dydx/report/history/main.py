from dataclasses import dataclass
from datetime import datetime
import asyncio

from tribulnation.sdk.reporting import History as _History
from dydx import Dydx
from .bigquery import BigQueryClient, BigQueryHistory
from .chain import ChainHistory, BlockTimeCache
from .indexer import IndexerHistory
from .governance import GovernanceHistory

@dataclass(kw_only=True)
class History(_History):
  address: str
  bigquery: BigQueryHistory | None = None
  chain: ChainHistory
  indexer: IndexerHistory
  governance: GovernanceHistory

  async def __aenter__(self):
    await asyncio.gather(
      self.chain.__aenter__(),
      self.indexer.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      self.chain.__aexit__(exc_type, exc_value, traceback),
      self.indexer.__aexit__(exc_type, exc_value, traceback),
    )

  @classmethod
  def of(
    cls, address: str, *,
    bigquery: BigQueryClient | None = None,
    dydx: Dydx | None = None,
    block_time_cache: BlockTimeCache | None = None,
    require_bigquery: bool = True
  ):
    if dydx is None:
      dydx = Dydx.kingnodes_archive(public=True)
    if require_bigquery and bigquery is None:
      bigquery = BigQueryClient()
    return cls(
      address=address,
      bigquery=BigQueryHistory.of(address, bigquery),
      chain=ChainHistory.of(address, dydx, block_time_cache),
      indexer=IndexerHistory.of(address, dydx),
      governance=GovernanceHistory(address),
    )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    coros = [
      self.chain.history(start, end),
      self.indexer.history(start, end),
      self.governance.history(start, end),
    ]
    if self.bigquery is not None:
      coros += (self.bigquery.history(start, end),)
    
    for task in asyncio.as_completed(coros):
      page = await task
      for record in page:
        yield record
