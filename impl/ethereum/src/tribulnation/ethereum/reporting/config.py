from typing_extensions import Literal, TypedDict
from tribulnation.ethereum.core import Network

SnapshotSource = Literal['alchemy', 'moralis', 'node']
HistorySource = Literal['etherscan', 'moralis']

class SnapshotSourcesConfig(TypedDict, total=False):
  snapshot: SnapshotSource
  """Default: `alchemy`.
  - Used by `snapshots(assets=None)`.
  - Sources may combine asset discovery and balance retrieval in one call."""
  snapshot_assets: SnapshotSource
  """Default: `node`.
  - Used by `snapshots(assets=...)` and open-ended `records()` reports.
  - `node` requires the asset contract set to be known."""

DEFAULT_SNAPSHOT_SOURCE: SnapshotSource = 'alchemy'
DEFAULT_SNAPSHOT_ASSETS_SOURCE: SnapshotSource = 'alchemy'

class HistorySourcesConfig(TypedDict, total=False):
  history: HistorySource
  """Default: `etherscan` for Ethereum, Arbitrum, and Polygon; `moralis` for the rest."""

DEFAULT_HISTORY_SOURCES: dict[Network, HistorySource] = {
  'ethereum': 'etherscan',
  'arbitrum': 'etherscan',
  'polygon': 'etherscan',
  'bnb': 'moralis',
  'base': 'moralis',
  'avalanche': 'moralis',
  'optimism': 'moralis',
}

class EvmSourcesConfig(SnapshotSourcesConfig, HistorySourcesConfig):
  ...

class EvmConfig(TypedDict, total=False):
  """EVM reporting configuration."""
  sources: EvmSourcesConfig
  """Source configuration by reporting bucket."""
  rpc_url: str
  """RPC URL override."""
  archive_rpc_url: str
  """Archive RPC URL override."""

NATIVE_ASSET = 'native'