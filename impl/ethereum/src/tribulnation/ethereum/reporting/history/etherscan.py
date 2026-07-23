from collections.abc import Iterable
from typing import AsyncContextManager
from typing_extensions import Literal, Awaitable, Callable, TypeVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import asyncio

from web3 import Web3
from etherscan import Etherscan
from etherscan.api.account.transactions import Transaction as NativeTransaction
from etherscan.api.account.token_transactions import TokenTransaction, token_value
from etherscan.api.account.internal_transactions import InternalTransaction
from etherscan.api.account.nft_transactions import NftTransaction

from tribulnation.sdk.core import SDK, managed_tasks
from tribulnation.sdk.reporting import History, Record, EvmTx, source_id
from tribulnation.ethereum.core import Network, etherscan as etherscan_core, group_by, same_address
from tribulnation.ethereum.reporting.util import AutoDetect, AUTO_DETECT, cached_etherscan
from tribulnation.ethereum.reporting.history.mixin import HistoryMixin

T = TypeVar('T')
TransactionGroups = dict[
  str,
  tuple[
    list[NativeTransaction],
    list[TokenTransaction],
    list[NftTransaction],
    list[InternalTransaction],
  ],
]

@dataclass(frozen=True, kw_only=True)
class EtherscanHistory(HistoryMixin, History):
  """Etherscan-backed EVM history source."""
  etherscan: Etherscan = field(default_factory=cached_etherscan)
  chain_id: int
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""
  batch_size: int = 4

  @classmethod
  def new(cls, address: str, *, network: Network, rpc_url: str | None = None, api_key: str | None = None, rate_limit: int | None = None):
    from tribulnation.ethereum.core import rpc, CHAIN_IDS
    from tribulnation.ethereum.reporting.util import cached_etherscan
    node, rpc_url = rpc.new(network, rpc_url, preferred='alchemy')
    etherscan = cached_etherscan(api_key=api_key, rate_limit=rate_limit)
    return cls(
      address=address, chain_id=CHAIN_IDS[network],
      node=node, rpc_url=rpc_url, etherscan=etherscan,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.etherscan

  @property
  def timezone(self) -> timezone:
    """Return the timezone used by Etherscan timestamps."""
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo  # type: ignore
    return self.tz

  def add_tz(self, time: datetime) -> datetime:
    """Attach the configured timezone to a naive timestamp."""
    return time.replace(tzinfo=self.timezone)

  @SDK.method
  @etherscan_core.wrap_exceptions
  async def get_block_by_time(self, time: datetime, closest: Literal['before', 'after'] = 'before') -> int:
    """Resolve a timestamp to the closest Etherscan block number."""
    return await self.etherscan.blocks.block_by_time(time, self.chain_id, closest=closest)

  @SDK.method
  @etherscan_core.wrap_exceptions
  async def call_etherscan(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Etherscan under the SDK exception wrapper."""
    return await fn()

  @SDK.method
  async def native_transactions(self, start_block: int, end_block: int) -> list[NativeTransaction]:
    """Fetch native transactions from Etherscan."""
    paging = self.etherscan.account.transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[NativeTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out

  @SDK.method
  async def token_transactions(self, start_block: int, end_block: int) -> list[TokenTransaction]:
    """Fetch ERC20 token transactions from Etherscan."""
    paging = self.etherscan.account.token_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[TokenTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out
  
  @SDK.method
  async def nft_transactions(self, start_block: int, end_block: int) -> list[NftTransaction]:
    """Fetch ERC721 token transactions from Etherscan."""
    paging = self.etherscan.account.nft_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[
      NftTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out

  @SDK.method
  async def internal_transactions(self, start_block: int, end_block: int) -> list[InternalTransaction]:
    """Fetch internal native transactions from Etherscan."""
    paging = self.etherscan.account.internal_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[InternalTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out


  async def fetch_limits(self, start: datetime | None = None, end: datetime | None = None) -> tuple[int, int]:
    """Fetch limiting blocks for the given time range."""
    async def get_start():
      """Resolve the first block to request."""
      if start is None:
        return 0
      else:
        return await self.get_block_by_time(start, 'before')

    async def get_end():
      """Resolve the last block to request."""
      if end is None:
        return await self.call_etherscan(lambda: self.etherscan.proxy.eth_block_number(chain_id=self.chain_id))
      else:
        return await self.get_block_by_time(end, 'after')

    async with managed_tasks((get_start(), get_end())) as tasks:
      start_block, end_block = await asyncio.gather(*tasks)
    return start_block, end_block

  async def fetch_all_transactions(
    self, start: datetime | None = None, end: datetime | None = None,
  ) -> TransactionGroups:
    """Fetch all transactions for the given time range."""
    start_block, end_block = await self.fetch_limits(start, end)
    native_task = asyncio.create_task(
      self.native_transactions(start_block, end_block),
    )
    token_task = asyncio.create_task(
      self.token_transactions(start_block, end_block),
    )
    nft_task = asyncio.create_task(
      self.nft_transactions(start_block, end_block),
    )
    internal_task = asyncio.create_task(
      self.internal_transactions(start_block, end_block),
    )
    tasks = (native_task, token_task, nft_task, internal_task)
    async with managed_tasks(tasks):
      all_native = await native_task
      all_token_txs = await token_task
      all_nft_txs = await nft_task
      all_internal_txs = await internal_task
    grouped_native: dict[str, list[NativeTransaction]] = group_by(
      all_native, lambda tx: tx['hash'],
    )
    grouped_token_txs: dict[str, list[TokenTransaction]] = group_by(
      all_token_txs, lambda tx: tx['hash'],
    )
    grouped_nft_txs: dict[str, list[NftTransaction]] = group_by(
      all_nft_txs, lambda tx: tx['hash'],
    )
    grouped_internal_txs: dict[str, list[InternalTransaction]] = group_by(
      all_internal_txs, lambda tx: tx['hash'],
    )
    hashes = set.union(
      set(grouped_native),
      set(grouped_token_txs),
      set(grouped_nft_txs),
      set(grouped_internal_txs),
    )
    transactions: TransactionGroups = {}
    for hash in hashes:
      transactions[hash] = (
        grouped_native.get(hash, []),
        grouped_token_txs.get(hash, []),
        grouped_nft_txs.get(hash, []),
        grouped_internal_txs.get(hash, []),
      )
    return transactions

  def parse_internal_txs(self, internal_txs: list[InternalTransaction]) -> list[EvmTx.NativeTransfer]:
    """Parse internal Etherscan rows into SDK native transfers."""
    return [
      transfer for tx in internal_txs
      if (transfer := self.parse_native_transfer(tx, internal=True)) is not None # type: ignore
    ]

  def parse_token_tx(self, token_tx: TokenTransaction) -> EvmTx.ERC20Transfer | None:
    """Parse an ERC20 Etherscan row into an SDK ERC20 transfer."""
    value = token_value(token_tx)
    if same_address(token_tx['to'], self.address):
      amount = value
      counterparty = token_tx['from']
    elif same_address(token_tx['from'], self.address):
      amount = -value
      counterparty = token_tx['to']
    else:
      return None
    return EvmTx.ERC20Transfer(
      asset=Web3.to_checksum_address(token_tx['contractAddress']),
      change=amount,
      counterparty=counterparty,
    )

  def parse_token_txs(self, token_txs: list[TokenTransaction]) -> list[EvmTx.ERC20Transfer]:
    """Parse ERC20 Etherscan rows into SDK ERC20 transfers."""
    return [
      transfer for tx in token_txs
      if (transfer := self.parse_token_tx(tx)) is not None
    ]
  
  def parse_nft_tx(self, nft_tx: NftTransaction) -> EvmTx.NftTransfer | None:
    """Parse an ERC721 Etherscan row into an SDK ERC721 transfer."""
    if same_address(nft_tx['to'], self.address):
      sign = 1
      counterparty = nft_tx['from']
    elif same_address(nft_tx['from'], self.address):
      sign = -1
      counterparty = nft_tx['to']
    else:
      return None
    return EvmTx.NftTransfer(
      contract_address=nft_tx['contractAddress'],
      token_id=nft_tx['tokenID'],
      change=Decimal(sign),
      counterparty=counterparty,
    )

  def parse_nft_txs(self, nft_txs: list[NftTransaction]) -> list[EvmTx.NftTransfer]:
    """Parse ERC721 Etherscan rows into SDK ERC721 transfers."""
    return [
      transfer for tx in nft_txs
      if (transfer := self.parse_nft_tx(tx)) is not None
    ]

  async def parse_tx(
    self, hash: str, *,
    native: list[NativeTransaction],
    token: list[TokenTransaction],
    nft: list[NftTransaction],
    internal: list[InternalTransaction]
  ) -> EvmTx | None:
    if len(native) > 1:
      raise ValueError('Multiple native transactions')
    all_txs = native + token + nft + internal
    any_tx = all_txs[0]
    time = self.add_tz(any_tx['timeStamp'])
    tx, receipt = await self.get_tx_data(hash)

    if receipt['status'] == 0:
      transfers = []
    else:
      transfers: list[EvmTx.Transfer] = (
        self.parse_native_transfers(tx)
        + self.parse_token_txs(token)
        + self.parse_nft_txs(nft)
        + self.parse_internal_txs(internal)
      )

    return EvmTx(
      id=hash, tx_id=hash,
      time=time,
      fee=self.parse_fee(tx, receipt),
      transfers=transfers,
      execution=await self.parse_execution(tx, receipt),
    )

  async def history(self, start: datetime | None = None, end: datetime | None = None):
    id = source_id('etherscan')
    transactions = await self.fetch_all_transactions(start, end)
    semaphore = asyncio.Semaphore(self.batch_size)
    async def parse_limited(
      hash: str,
      native: list[NativeTransaction],
      token: list[TokenTransaction],
      nft: list[NftTransaction],
      internal: list[InternalTransaction],
    ):
      async with semaphore:
        return await self.parse_tx(hash, native=native, token=token, nft=nft, internal=internal)

    coros = [
      parse_limited(hash, native, token, nft, internal)
      for hash, (native, token, nft, internal) in transactions.items()
    ]
    async with managed_tasks(coros) as tasks:
      for task in asyncio.as_completed(tasks):
        tx = await task
        if tx is not None:
          yield Record(observations=[tx], provenance={'source': 'api', 'service': 'etherscan', 'id': id})
