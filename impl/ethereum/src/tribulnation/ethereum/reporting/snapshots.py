"""Unified EVM reporting snapshots."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

from alchemy import Alchemy
from ethereum import NodeRpc
from moralis import Moralis
from typing_extensions import Collection, Sequence
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from tribulnation.sdk import ApiError, SDK
from tribulnation.sdk.reporting import Balance, Record, Snapshot, Snapshots as _Snapshots

from tribulnation.ethereum.core import rpc
from .config import EvmConfig, EvmNetwork
from .constants import (
  ALCHEMY_NETWORKS,
  DEFAULT_ASSETS_SOURCE,
  DEFAULT_SNAPSHOT_ASSETS_SOURCE,
  MORALIS_CHAINS,
)


NATIVE_ASSET = 'native'
NATIVE_DECIMALS = 18


def hex_balance(value: str) -> int:
  """Parse an Alchemy hex-encoded balance."""
  return int(value, 16) if value.startswith('0x') else int(value)


def token_qty(value: str, decimals: int | None) -> Decimal:
  """Convert a raw integer token balance into display units."""
  return Decimal(hex_balance(value)) * (Decimal(10) ** -(decimals or NATIVE_DECIMALS))


@dataclass(frozen=True)
class Snapshots(_Snapshots):
  """EVM snapshots from configured full-snapshot or known-asset sources."""
  address: str
  network: EvmNetwork
  chain_id: int
  config: EvmConfig
  node: NodeRpc | None = None
  alchemy: Alchemy | None = None
  moralis: Moralis | None = None
  ignore_bad_contracts: bool = True
  ignore_zero_value: bool = True

  async def __aenter__(self):
    """Open configured snapshot transports."""
    await asyncio.gather(*[
      client.__aenter__()
      for client in (
        self.node,
        self.alchemy,
        getattr(self, 'alchemy_transfers', None),
        getattr(self, 'etherscan', None),
        self.moralis,
      )
      if client is not None
    ])
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    """Close configured snapshot transports."""
    await asyncio.gather(*[
      client.__aexit__(exc_type, exc_value, traceback)
      for client in (
        self.node,
        self.alchemy,
        getattr(self, 'alchemy_transfers', None),
        getattr(self, 'etherscan', None),
        self.moralis,
      )
      if client is not None
    ])

  def source(self, key: str, default: str) -> str:
    """Return the configured source for one EVM snapshot bucket."""
    return self.config.get('sources', {}).get(key, default)

  def require_node(self) -> NodeRpc:
    """Return the configured node client or raise a concrete configuration error."""
    if self.node is None:
      raise ValueError('EVM node-backed snapshots require an RPC client.')
    return self.node

  def require_alchemy(self) -> Alchemy:
    """Return the configured Alchemy client or raise a concrete configuration error."""
    if self.alchemy is None:
      raise ValueError('EVM Alchemy snapshots require an Alchemy provider.')
    return self.alchemy

  def require_moralis(self) -> Moralis:
    """Return the configured Moralis client or raise a concrete configuration error."""
    if self.moralis is None:
      raise ValueError('EVM Moralis snapshots require a Moralis provider.')
    return self.moralis

  @SDK.method
  @rpc.wrap_exceptions
  async def eth_balance(self) -> Decimal:
    """Fetch the native token balance from the configured node."""
    return Decimal(await self.require_node().eth_balance(self.address))

  @SDK.method
  @rpc.wrap_exceptions
  async def token_balance(self, contract: str) -> Decimal | None:
    """Fetch an ERC20 token balance from the configured node."""
    try:
      return Decimal(await self.require_node().token(contract).balance(self.address))
    except (ContractLogicError, BadFunctionCallOutput) as exc:
      if not self.ignore_bad_contracts:
        raise ApiError(f'Contract {contract} raised a logic error', *exc.args) from exc
      return None

  @rpc.wrap_exceptions
  async def node_snapshots(self, assets: Collection[str]) -> Record:
    """Snapshot native balance and known ERC20 balances from the configured node."""
    time = datetime.now(timezone.utc)
    balances: dict[str, Balance] = {
      NATIVE_ASSET: Balance(qty=await self.eth_balance(), kind='currency'),
    }
    contracts = [
      Web3.to_checksum_address(contract)
      for contract in assets
      if contract != NATIVE_ASSET
    ]
    for contract in contracts:
      balance = await self.token_balance(contract)
      if balance is not None and (not self.ignore_zero_value or balance > 0):
        balances[contract] = Balance(qty=balance, kind='currency')
    return Record(
      snapshots=[Snapshot(time=time, balances=balances)],
      provenance={'source': 'api', 'service': 'node_rpc'},
    )

  async def alchemy_snapshots(self, assets: Sequence[str] | None = None) -> Record:
    """Snapshot wallet balances with Alchemy Portfolio tokens."""
    client = self.require_alchemy()
    wanted = {Web3.to_checksum_address(asset) for asset in assets or [] if asset != NATIVE_ASSET}
    tokens = await client.portfolio.tokens.paged({
      'addresses': [{
        'address': self.address,
        'networks': [ALCHEMY_NETWORKS[self.network]],
      }],
      'withMetadata': True,
      'withPrices': True,
      'includeNativeTokens': True,
      'includeErc20Tokens': True,
    })
    balances: dict[str, Balance] = {}
    for token in tokens:
      address = token.get('tokenAddress')
      metadata = token.get('tokenMetadata') or {}
      asset = NATIVE_ASSET if address is None else Web3.to_checksum_address(address)
      if assets is not None and asset != NATIVE_ASSET and asset not in wanted:
        continue
      qty = token_qty(token['tokenBalance'], metadata.get('decimals'))
      if not self.ignore_zero_value or qty > 0:
        balances[asset] = Balance(qty=qty, kind='currency')
    return Record(
      snapshots=[Snapshot(time=datetime.now(timezone.utc), balances=balances)],
      provenance={'source': 'api', 'service': 'alchemy', 'endpoint': 'portfolio.tokens'},
    )

  async def moralis_snapshots(self) -> Record:
    """Snapshot wallet balances with Moralis token balances."""
    client = self.require_moralis()
    balances: dict[str, Balance] = {}
    tokens = await client.evm.wallet.token_balances_paged(
      self.address,
      chain=MORALIS_CHAINS[self.network],
      exclude_spam=True,
    )
    for token in tokens:
      address = token['token_address']
      asset = NATIVE_ASSET if token.get('native_token') else Web3.to_checksum_address(address)
      balance = token.get('balance_formatted')
      if balance is None:
        decimals = token.get('decimals') or NATIVE_DECIMALS
        qty = Decimal(token['balance']) * (Decimal(10) ** -decimals)
      else:
        qty = Decimal(balance)
      if not self.ignore_zero_value or qty > 0:
        balances[asset] = Balance(qty=qty, kind='currency')
    return Record(
      snapshots=[Snapshot(time=datetime.now(timezone.utc), balances=balances)],
      provenance={'source': 'api', 'service': 'moralis', 'endpoint': 'wallet.token_balances'},
    )

  @SDK.method
  async def snapshots(self, assets: Collection[str] | None = None) -> Record:
    """Fetch an EVM snapshot from the configured source."""
    if assets is None:
      source = self.source('assets', DEFAULT_ASSETS_SOURCE)
      if source == 'alchemy':
        return await self.alchemy_snapshots()
      if source == 'moralis':
        return await self.moralis_snapshots()
      if source == 'etherscan':
        raise NotImplementedError('Etherscan-backed full asset snapshots are not implemented.')
      raise ValueError(f'Invalid EVM assets source: {source}')

    source = self.source('snapshot_assets', DEFAULT_SNAPSHOT_ASSETS_SOURCE)
    if source == 'node':
      return await self.node_snapshots(assets)
    if source == 'alchemy':
      return await self.alchemy_snapshots(assets=sorted(assets))
    raise ValueError(f'Invalid EVM snapshot_assets source: {source}')
