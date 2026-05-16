"""EVM reporting configuration types."""

from typing_extensions import Literal, TypedDict


EvmNetwork = Literal[
  'ethereum',
  'arbitrum',
  'polygon',
  'bnb',
  'base',
  'avalanche',
  'optimism',
]
"""Supported EVM reporting network."""


class EvmSourcesConfig(TypedDict, total=False):
  """Source selection for each EVM reporting bucket."""
  assets: Literal['alchemy', 'moralis', 'etherscan']
  """Default: `alchemy`.
  - Used by `snapshots(assets=None)`.
  - Sources may combine asset discovery and balance retrieval in one call."""
  snapshot_assets: Literal['node', 'alchemy']
  """Default: `node`.
  - Used by `snapshots(assets=...)` and open-ended `records()` reports.
  - `node` requires the asset contract set to be known."""
  history: Literal['etherscan', 'alchemy', 'moralis']
  """Default: `etherscan` for Ethereum, Arbitrum, and Polygon; `moralis` for the rest."""


class EvmConfig(TypedDict, total=False):
  """EVM reporting configuration."""
  sources: EvmSourcesConfig
  """Source configuration by reporting bucket."""
  rpc_url: str
  """Network RPC URL override."""
  validate: bool
  """Enable typed provider response validation."""
