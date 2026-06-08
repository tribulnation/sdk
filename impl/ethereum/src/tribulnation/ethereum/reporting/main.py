from typing_extensions import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio

from tribulnation.sdk.reporting import Report, History, Snapshots, Record, EvmTx, Snapshot, ProvidersConfig
from tribulnation.ethereum.core import Network
from .config import EvmConfig
from .util import source_id

@dataclass
class EthereumReport(Report):
  address: str
  history_impl: History
  snapshots_impl: Snapshots
  asset_snapshots_impl: Snapshots

  @classmethod
  def new(cls, address: str, *, network: Network, config: EvmConfig | None = None, providers: ProvidersConfig | None = None):
    from .history import EthereumHistory
    from .snapshots import EthereumSnapshots
    config = config or {}
    sources = config.get('sources', {})
    rpc_url = config.get('rpc_url')
    archive_rpc_url = config.get('archive_rpc_url')
    history_impl = EthereumHistory.new(address, network=network, source=sources.get('history'), rpc_url=archive_rpc_url, providers=providers)
    snapshots_impl = EthereumSnapshots.new(address, network=network, source=sources.get('snapshot'), rpc_url=rpc_url, providers=providers)
    asset_snapshots_impl = EthereumSnapshots.new(address, network=network, source=sources.get('snapshot_assets'), rpc_url=rpc_url, providers=providers)
    return cls(address=address, history_impl=history_impl, snapshots_impl=snapshots_impl, asset_snapshots_impl=asset_snapshots_impl)

  async def __aenter__(self):
    await asyncio.gather(
      self.history_impl.__aenter__(),
      self.snapshots_impl.__aenter__(),
      self.asset_snapshots_impl.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      self.history_impl.__aexit__(exc_type, exc_value, traceback),
      self.snapshots_impl.__aexit__(exc_type, exc_value, traceback),
      self.asset_snapshots_impl.__aexit__(exc_type, exc_value, traceback),
    )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    async for record in self.history_impl.history(start, end):
      yield record

  async def snapshots(self, assets: Sequence[str] | None = None):
    return await self.snapshots_impl.snapshots(assets)

  async def records(self, start: datetime | None = None, end: datetime | None = None):
    assets = set[str]()
    start_time: datetime | None = None
    async for record in self.history(start, end):
      yield record
      for obs in record.observations:
        if obs.time is not None:
          start_time = obs.time if start_time is None else min(start_time, obs.time)
        if isinstance(obs, EvmTx):
          for transfer in obs.transfers:
            assets.add(transfer.asset)

    if start is None and start_time is not None:
      snapshot_time = start_time - timedelta(days=1)
      yield Record(
        snapshots=[Snapshot(time=snapshot_time, balances={})],
        provenance={
          'source': 'derived',
          'id': source_id('derived'),
          'details': {
            'note': 'EVM full-history reports imply zero balances before the first observed transaction.',
          },
        },
      )

    if end is None:
      yield await self.asset_snapshots_impl.snapshots(assets=sorted(assets))