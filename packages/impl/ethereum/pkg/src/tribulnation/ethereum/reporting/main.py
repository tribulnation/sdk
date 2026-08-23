from collections.abc import Iterable
from typing_extensions import AsyncContextManager, Collection
from dataclasses import dataclass
from datetime import datetime

from tribulnation.sdk.reporting import (
  Report, History, Snapshots,
  SnapshotRecord, ProvidersConfig,
)
from tribulnation.ethereum.core import Network
from .config import EvmConfig

@dataclass(frozen=True)
class EthereumReport(Report):
  address: str
  history_impl: History
  snapshots_impl: Snapshots

  @classmethod
  def new(cls, address: str, *, network: Network, config: EvmConfig | None = None, providers: ProvidersConfig | None = None):
    from .history import EthereumHistory
    from .snapshots import EthereumSnapshots
    config = config or {}
    sources = config.get('sources', {})
    rpc_url = config.get('rpc_url')
    archive_rpc_url = config.get('archive_rpc_url')
    history_impl = EthereumHistory.new(
      address, network=network, source=sources.get('history'),
      rpc_url=archive_rpc_url, providers=providers,
    )
    snapshots_impl = EthereumSnapshots.new(
      address, network=network, source=sources.get('snapshot'),
      rpc_url=rpc_url, providers=providers,
    )
    return cls(address=address, history_impl=history_impl, snapshots_impl=snapshots_impl)

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.history_impl
    yield self.snapshots_impl

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    async for record in self.history_impl.history(start, end):
      yield record

  async def snapshot(self, assets: Collection[str] | None = None) -> SnapshotRecord:
    return await self.snapshots_impl.snapshot(assets)
