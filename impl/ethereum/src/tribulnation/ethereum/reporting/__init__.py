"""EVM reporting clients."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import os

from alchemy import Alchemy
from alchemy.core import (
  ARBITRUM_ALCHEMY_RPC_URL,
  AVAX_ALCHEMY_RPC_URL,
  BASE_ALCHEMY_RPC_URL,
  BNB_ALCHEMY_RPC_URL,
  ETHEREUM_ALCHEMY_RPC_URL,
  OPTIMISM_ALCHEMY_RPC_URL,
  POLYGON_ALCHEMY_RPC_URL,
)
from alchemy.api.transfers import Transfers
from etherscan import Etherscan
from ethereum import NodeRpc, PUBLIC_NODE_URLS
from moralis import Moralis
from typing_extensions import AsyncIterable
from typed_core import AuthError

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import EvmTx, ProvidersConfig, Record, Report as _Report, Snapshot
from .config import EvmConfig, EvmNetwork
from .constants import (
  DEFAULT_ASSETS_SOURCE,
  DEFAULT_HISTORY_SOURCES,
  DEFAULT_SNAPSHOT_ASSETS_SOURCE,
  POA_NETWORKS,
  RPC_ENV_VARS,
  CHAIN_IDS,
)
from .history import History
from .snapshots import Snapshots


ALCHEMY_RPC_URLS: dict[EvmNetwork, str] = {
  'ethereum': ETHEREUM_ALCHEMY_RPC_URL,
  'arbitrum': ARBITRUM_ALCHEMY_RPC_URL,
  'polygon': POLYGON_ALCHEMY_RPC_URL,
  'bnb': BNB_ALCHEMY_RPC_URL,
  'base': BASE_ALCHEMY_RPC_URL,
  'avalanche': AVAX_ALCHEMY_RPC_URL,
  'optimism': OPTIMISM_ALCHEMY_RPC_URL,
}


@dataclass(frozen=True)
class Report(Snapshots, History, _Report):
  """EVM reporting client with source-dispatched snapshots and history."""
  address: str = ''
  network: EvmNetwork = 'ethereum'
  chain_id: int = 1
  config: EvmConfig = field(default_factory=lambda: {})
  node: NodeRpc | None = None
  etherscan: Etherscan | None = None
  alchemy: Alchemy | None = None
  alchemy_transfers: Transfers | None = None
  moralis: Moralis | None = None
  include_internal_transfers: bool = False
  batch_size: int = 32
  ignore_bad_contracts: bool = True
  ignore_zero_value: bool = True

  @staticmethod
  def optional_alchemy(api_key: str | None, *, validate: bool) -> Alchemy | None:
    """Create an Alchemy client when credentials are available."""
    try:
      return Alchemy.new(api_key=api_key, validate=validate)
    except AuthError:
      return None

  @staticmethod
  def optional_moralis(api_key: str | None, *, validate: bool) -> Moralis | None:
    """Create a Moralis client when credentials are available."""
    try:
      return Moralis.new(api_key, validate=validate)
    except AuthError:
      return None

  @staticmethod
  def optional_etherscan(
    api_key: str | None, *, validate: bool, rate_limit: int | None,
  ) -> Etherscan | None:
    """Create an Etherscan client when credentials are available."""
    try:
      return Etherscan.new(api_key=api_key, validate=validate, rate_limit=rate_limit)
    except KeyError as exc:
      if exc.args == ('ETHERSCAN_API_KEY',):
        return None
      raise

  @classmethod
  def new(
    cls, address: str, *, network: EvmNetwork,
    config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create an EVM reporting client for a supported network.

    Args:
      address: Wallet address to report.
      network: EVM network identifier.
      config: EVM source and RPC configuration.
      providers: Shared reporting provider credentials.
    """
    config = config or {}
    sources = config.get('sources', {})
    validate = config.get('validate', True)
    assets_source = sources.get('assets', DEFAULT_ASSETS_SOURCE)
    snapshot_assets_source = sources.get('snapshot_assets', DEFAULT_SNAPSHOT_ASSETS_SOURCE)
    history_source = sources.get('history', DEFAULT_HISTORY_SOURCES[network])
    provider_config = providers or {}

    rpc_url = (
      config.get('rpc_url')
      or os.environ.get(RPC_ENV_VARS[network])
      or PUBLIC_NODE_URLS[network]
    )
    needs_node = snapshot_assets_source == 'node' or history_source in {'etherscan', 'alchemy'}
    node = NodeRpc.at(rpc_url, poa_middleware=network in POA_NETWORKS) if needs_node else None

    alchemy_provider = provider_config.get('alchemy')
    alchemy_api_key = alchemy_provider.get('api_key') if alchemy_provider is not None else None
    requires_alchemy = snapshot_assets_source == 'alchemy' or history_source == 'alchemy'
    wants_alchemy = assets_source == 'alchemy' or requires_alchemy
    alchemy = (
      Alchemy.new(api_key=alchemy_api_key, validate=validate)
      if requires_alchemy
      else cls.optional_alchemy(alchemy_api_key, validate=validate) if wants_alchemy else None
    )
    alchemy_transfers = (
      Transfers.new(ALCHEMY_RPC_URLS[network], api_key=alchemy_api_key, validate=validate)
      if history_source == 'alchemy'
      else None
    )

    etherscan_provider = provider_config.get('etherscan')
    etherscan_api_key = etherscan_provider.get('api_key') if etherscan_provider is not None else None
    etherscan_rate_limit = etherscan_provider.get('rate_limit') if etherscan_provider is not None else None
    needs_etherscan = assets_source == 'etherscan' or history_source == 'etherscan'
    etherscan = (
      cls.optional_etherscan(
        etherscan_api_key,
        validate=validate,
        rate_limit=etherscan_rate_limit,
      )
      if needs_etherscan
      else None
    )

    moralis_provider = provider_config.get('moralis')
    moralis_api_key = moralis_provider.get('api_key') if moralis_provider is not None else None
    requires_moralis = history_source == 'moralis'
    wants_moralis = assets_source == 'moralis' or requires_moralis
    moralis = (
      Moralis.new(moralis_api_key, validate=validate)
      if requires_moralis
      else cls.optional_moralis(moralis_api_key, validate=validate) if wants_moralis else None
    )

    return cls(
      address=address,
      network=network,
      chain_id=CHAIN_IDS[network],
      config=config,
      node=node,
      etherscan=etherscan,
      alchemy=alchemy,
      alchemy_transfers=alchemy_transfers,
      moralis=moralis,
      include_internal_transfers=network in {'ethereum', 'polygon'},
    )

  @classmethod
  def ethereum(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create an Ethereum mainnet reporting client."""
    return cls.new(address, network='ethereum', config=config, providers=providers)

  @classmethod
  def arbitrum(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create an Arbitrum reporting client."""
    return cls.new(address, network='arbitrum', config=config, providers=providers)

  @classmethod
  def polygon(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create a Polygon reporting client."""
    return cls.new(address, network='polygon', config=config, providers=providers)

  @classmethod
  def bnb(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create a BNB Chain reporting client."""
    return cls.new(address, network='bnb', config=config, providers=providers)

  @classmethod
  def base(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create a Base reporting client."""
    return cls.new(address, network='base', config=config, providers=providers)

  @classmethod
  def avalanche(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create an Avalanche reporting client."""
    return cls.new(address, network='avalanche', config=config, providers=providers)

  @classmethod
  def optimism(
    cls, address: str, *, config: EvmConfig | None = None,
    providers: ProvidersConfig | None = None,
  ) -> 'Report':
    """Create an Optimism reporting client."""
    return cls.new(address, network='optimism', config=config, providers=providers)

  @SDK.method
  async def records(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch EVM records with a derived zero baseline and current snapshot."""
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
          'method': 'evm_zero_baseline_snapshot',
          'reason': 'EVM full-history reports imply zero balances before the first observed transaction.',
        },
      )

    if end is None:
      yield await self.snapshots(assets=sorted(assets))


Reporting = Report
