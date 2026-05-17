"""Unified EVM reporting history dispatch."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio

from alchemy.api.transfers import Transfers
from etherscan import Etherscan
from ethereum import NodeRpc
from moralis import Moralis
from typing_extensions import AsyncIterable
from web3.types import BlockIdentifier

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import History as _History, Record
from .alchemy import AlchemyHistory
from .etherscan import AUTO_DETECT, AutoDetect, EtherscanHistory
from .moralis import MoralisHistory
from ..config import EvmConfig, EvmNetwork
from ..constants import DEFAULT_HISTORY_SOURCES


@dataclass(frozen=True, kw_only=True)
class History(EtherscanHistory, AlchemyHistory, MoralisHistory, _History):
  """EVM reporting history from the configured evidence source."""
  address: str
  network: EvmNetwork
  chain_id: int
  config: EvmConfig
  node: NodeRpc | None = None
  etherscan: Etherscan | None = None
  alchemy_transfers: Transfers | None = None
  moralis: Moralis | None = None
  include_internal_transfers: bool = False
  batch_size: int = 32
  tz: timezone | AutoDetect = AUTO_DETECT
  block_time_cache: dict[int, datetime] = field(default_factory=dict)
  block_timestamps_cache: dict[BlockIdentifier, asyncio.Future[datetime]] = field(default_factory=dict)

  def source(self, key: str, default: str) -> str:
    """Return the configured source for one EVM history bucket."""
    return self.config.get('sources', {}).get(key, default)

  @SDK.method
  async def history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch EVM history records from the configured provider."""
    source = self.source('history', DEFAULT_HISTORY_SOURCES[self.network])
    if source == 'etherscan':
      if self.etherscan is None:
        raise ValueError('EVM Etherscan history requires an Etherscan provider.')
      async for record in self.etherscan_history(start, end):
        yield record
    elif source == 'alchemy':
      if self.alchemy_transfers is None:
        raise ValueError('EVM Alchemy history requires an Alchemy provider.')
      async for record in self.alchemy_history(start, end):
        yield record
    elif source == 'moralis':
      async for record in self.moralis_history(start, end):
        yield record
    else:
      raise ValueError(f'Invalid EVM history source: {source}')
