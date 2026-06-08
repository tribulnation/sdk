from dataclasses import dataclass as _dataclass
from datetime import datetime as _datetime

from tribulnation.sdk.reporting import History as _History, ProvidersConfig as _ProvidersConfig
from tribulnation.ethereum.core import Network
from ..config import HistorySource, DEFAULT_HISTORY_SOURCES

@_dataclass
class EthereumHistory(_History):
  impl: _History

  async def __aenter__(self):
    await self.impl.__aenter__()
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await self.impl.__aexit__(exc_type, exc_value, traceback)

  async def history(self, start: _datetime | None = None, end: _datetime | None = None):
    async for record in self.impl.history(start, end):
      yield record

  @classmethod
  def etherscan(cls, address: str, *, network: Network, rpc_url: str | None = None, api_key: str | None = None, rate_limit: int | None = None):
    from tribulnation.ethereum.core import rpc, CHAIN_IDS
    from tribulnation.ethereum.reporting.util import cached_etherscan
    from .etherscan import EtherscanHistory
    node, rpc_url = rpc.new(network, rpc_url, preferred='alchemy')
    etherscan = cached_etherscan(api_key=api_key, rate_limit=rate_limit)
    return EtherscanHistory(address=address, chain_id=CHAIN_IDS[network], node=node, rpc_url=rpc_url, etherscan=etherscan)

  @classmethod
  def moralis(cls, address: str, *, network: Network, api_key: str | None = None):
    from moralis import Moralis
    from tribulnation.ethereum.core.moralis import MORALIS_CHAINS
    from .moralis import MoralisHistory
    moralis = Moralis.new(api_key)
    return MoralisHistory(address=address, chain=MORALIS_CHAINS[network], moralis=moralis)

  @classmethod
  def new(
    cls, address: str, *, network: Network,
    source: HistorySource | None = None,
    rpc_url: str | None = None,
    providers: _ProvidersConfig | None = None,
  ):
    source = source or DEFAULT_HISTORY_SOURCES[network]
    providers = providers or {}
    if source == 'etherscan':
      config = providers.get('etherscan') or {}
      return cls.etherscan(address=address, network=network, rpc_url=rpc_url, api_key=config.get('api_key'), rate_limit=config.get('rate_limit'))
    elif source == 'moralis':
      config = providers.get('moralis') or {}
      return cls.moralis(address=address, network=network, api_key=config.get('api_key'))
    else:
      raise ValueError(f'Invalid history source: {source}')