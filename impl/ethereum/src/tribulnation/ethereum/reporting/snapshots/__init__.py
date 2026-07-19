from typing_extensions import Collection as _Collection
from dataclasses import dataclass as _dataclass
from tribulnation.sdk.reporting import (
  SnapshotResult as _SnapshotResult, Snapshots as _Snapshots,
  ProvidersConfig as _ProvidersConfig,
)
from tribulnation.ethereum.core import Network
from ..config import SnapshotSource, DEFAULT_SNAPSHOT_SOURCE

@_dataclass
class EthereumSnapshots(_Snapshots):
  impl: _Snapshots

  async def __aenter__(self):
    await self.impl.__aenter__()
    return self
    
  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.impl.__aexit__(exc_type, exc_value, traceback)

  async def snapshot(self, assets: _Collection[str] | None = None) -> _SnapshotResult:
    return await self.impl.snapshot(assets)

  @classmethod
  def node(cls, address: str, *, network: Network, rpc_url: str | None = None):
    from tribulnation.ethereum.core import rpc
    from .node import NodeSnapshots
    node, rpc_url = rpc.new(network, rpc_url)
    return NodeSnapshots(address=address, node=node, rpc_url=rpc_url)

  @classmethod
  def alchemy(cls, address: str, *, network: Network, api_key: str | None = None):
    from alchemy import Alchemy
    from tribulnation.ethereum.core.alchemy import ALCHEMY_NETWORKS
    from .alchemy import AlchemySnapshots
    alchemy = Alchemy.new(api_key=api_key)
    return AlchemySnapshots(address=address, network=ALCHEMY_NETWORKS[network], alchemy=alchemy)

  @classmethod
  def moralis(cls, address: str, *, network: Network, api_key: str | None = None):
    from moralis import Moralis
    from tribulnation.ethereum.core.moralis import MORALIS_CHAINS
    from .moralis import MoralisSnapshots
    moralis = Moralis.new(api_key)
    return MoralisSnapshots(address=address, chain=MORALIS_CHAINS[network], moralis=moralis)

  @classmethod
  def new(cls, address: str, *, network: Network, source: SnapshotSource | None = None, rpc_url: str | None = None, providers: _ProvidersConfig | None = None):
    source = source or DEFAULT_SNAPSHOT_SOURCE
    providers = providers or {}
    if source == 'node':
      return cls.node(address=address, network=network, rpc_url=rpc_url)
    elif source == 'alchemy':
      config = providers.get('alchemy') or {}
      return cls.alchemy(address=address, network=network, api_key=config.get('api_key'))
    elif source == 'moralis':
      config = providers.get('moralis') or {}
      return cls.moralis(address=address, network=network, api_key=config.get('api_key'))
    else:
      raise ValueError(f'Invalid snapshot source: {source}')
