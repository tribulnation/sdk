from typing_extensions import Literal, TypedDict
from tribulnation.ethereum.core import Network

SnapshotSource = Literal['alchemy', 'moralis', 'node']
HistorySource = Literal['etherscan', 'moralis']

class SnapshotSourcesConfig(TypedDict, total=False):
  snapshot: SnapshotSource
  """Default: `alchemy`.
  - Used by `snapshot()`, with or without an explicit asset set.
  - Sources may combine asset discovery and balance retrieval in one call;
    `node` cannot, and reports only the native asset unless assets are given."""

DEFAULT_SNAPSHOT_SOURCE: SnapshotSource = 'alchemy'

class HistorySourcesConfig(TypedDict, total=False):
  history: HistorySource
  """Default: `etherscan` for Ethereum, Arbitrum, Polygon, and HyperEVM; `moralis` for the rest."""

DEFAULT_HISTORY_SOURCES: dict[Network, HistorySource] = {
  'ethereum': 'etherscan',
  'arbitrum': 'etherscan',
  'polygon': 'etherscan',
  'bnb-chain': 'moralis',
  'base': 'moralis',
  'avalanche': 'moralis',
  'optimism': 'moralis',
  'hyperevm': 'etherscan',
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
