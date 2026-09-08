"""Etherscan-backed EVM history: the account feeds give the transfers and block times,
the node gives each transaction's receipt, input and bytecode check.
"""

from collections.abc import Iterable
from typing_extensions import (
  AsyncContextManager,
  Awaitable,
  Callable,
  Literal,
  TypeVar,
)
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import asyncio

from web3 import Web3
from typed_etherscan import Etherscan
from typed_etherscan.account.transactions import AccountTransaction as NativeTransaction
from typed_etherscan.account.erc20_transfers import Erc20Transfer as TokenTransaction
from typed_etherscan.account.erc721_transfers import Erc721Transfer as NftTransaction
from typed_etherscan.account.internal_transactions import InternalTransaction

from tribulnation.sdk.core import SDK, ApiError, managed_tasks
from tribulnation.sdk.reporting import History, HistoryRecord, EvmTx, source_id
from tribulnation.ethereum.core import (
  Network,
  etherscan as etherscan_core,
  group_by,
  same_address,
)
from tribulnation.ethereum.reporting.util import cached_etherscan
from tribulnation.ethereum.reporting.history.mixin import HistoryMixin

T = TypeVar('T')

FeedRow = NativeTransaction | TokenTransaction | NftTransaction | InternalTransaction
"""A row of any of the four account feeds; all of them carry `hash` and `timeStamp`."""


def token_value(tx: TokenTransaction) -> Decimal:
  """Return an ERC-20 transfer value in display units."""
  return Decimal(tx['value']) * (Decimal(10) ** -tx['tokenDecimal'])


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
  batch_size: int = 4
  page_size: int = 1000

  @classmethod
  def new(
    cls,
    address: str,
    *,
    network: Network,
    rpc_url: str | None = None,
    api_key: str | None = None,
    rate_limit: int | None = None,
  ):
    from tribulnation.ethereum.core import rpc, CHAIN_IDS

    node, rpc_url = rpc.new(network, rpc_url, preferred='alchemy')
    etherscan = cached_etherscan(api_key=api_key, rate_limit=rate_limit)
    return cls(
      address=address,
      chain_id=CHAIN_IDS[network],
      node=node,
      rpc_url=rpc_url,
      etherscan=etherscan,
    )

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield from super().resources()
    yield self.etherscan

  @property
  def chainid(self) -> str:
    """The chain id in the form Etherscan's v2 API takes it."""
    return str(self.chain_id)

  @SDK.method
  @etherscan_core.wrap_exceptions
  async def call_etherscan(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Etherscan under the SDK exception wrapper."""
    return await fn()

  @SDK.method
  async def get_block_by_time(
    self, time: datetime, closest: Literal['before', 'after'] = 'before'
  ) -> int:
    """Resolve a timestamp to the closest Etherscan block number."""
    response = await self.call_etherscan(
      lambda: self.etherscan.blocks.number_by_time(
        self.chainid, timestamp=time, closest=closest
      )
    )
    result = response['result']
    if response['status'] != '1' or not result.isdigit():
      raise ApiError(response['message'], result)
    return int(result)

  @SDK.method
  async def latest_block(self) -> int:
    """Fetch the chain head, for an open-ended window."""
    response = await self.call_etherscan(
      lambda: self.etherscan.proxy.eth_block_number(self.chainid)
    )
    if (result := response.get('result')) is None:
      raise ApiError(response.get('error'))
    return int(result, 16)

  @SDK.method
  async def native_transactions(
    self, start_block: int, end_block: int
  ) -> list[NativeTransaction]:
    """Fetch native transactions from Etherscan."""
    paging = self.etherscan.account.transactions_paged(
      address=self.address,
      chainid=self.chainid,
      startblock=start_block,
      endblock=end_block,
      offset=self.page_size,
      sort='asc',
    )
    return list(await paging.via(self.call_etherscan))

  @SDK.method
  async def token_transactions(
    self, start_block: int, end_block: int
  ) -> list[TokenTransaction]:
    """Fetch ERC-20 token transactions from Etherscan, over every contract."""
    paging = self.etherscan.account.erc20_transfers_paged(
      address=self.address,
      chainid=self.chainid,
      startblock=start_block,
      endblock=end_block,
      offset=self.page_size,
      sort='asc',
    )
    return list(await paging.via(self.call_etherscan))

  @SDK.method
  async def nft_transactions(
    self, start_block: int, end_block: int
  ) -> list[NftTransaction]:
    """Fetch ERC-721 token transactions from Etherscan, over every contract."""
    paging = self.etherscan.account.erc721_transfers_paged(
      address=self.address,
      chainid=self.chainid,
      startblock=start_block,
      endblock=end_block,
      offset=self.page_size,
      sort='asc',
    )
    return list(await paging.via(self.call_etherscan))

  @SDK.method
  async def internal_transactions(
    self, start_block: int, end_block: int
  ) -> list[InternalTransaction]:
    """Fetch internal native transactions from Etherscan."""
    paging = self.etherscan.account.internal_transactions_paged(
      address=self.address,
      chainid=self.chainid,
      startblock=start_block,
      endblock=end_block,
      offset=self.page_size,
      sort='asc',
    )
    return list(await paging.via(self.call_etherscan))

  async def fetch_limits(
    self, start: datetime | None = None, end: datetime | None = None
  ) -> tuple[int, int]:
    """Fetch limiting blocks for the given time range."""

    async def get_start():
      """Resolve the first block at or after `start`."""
      if start is None:
        return 0
      return await self.get_block_by_time(start, 'after')

    async def get_end():
      """Resolve the last block at or before `end`; the chain head when open."""
      if end is None:
        return await self.latest_block()
      return await self.get_block_by_time(end, 'before')

    async with managed_tasks((get_start(), get_end())) as tasks:
      start_block, end_block = await asyncio.gather(*tasks)
    return start_block, end_block

  async def fetch_all_transactions(
    self,
    start: datetime | None = None,
    end: datetime | None = None,
  ) -> TransactionGroups:
    """Fetch all transactions for the given time range, grouped by hash."""
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
    grouped_native = group_by(all_native, lambda tx: tx['hash'])
    grouped_token_txs = group_by(all_token_txs, lambda tx: tx['hash'])
    grouped_nft_txs = group_by(all_nft_txs, lambda tx: tx['hash'])
    grouped_internal_txs = group_by(all_internal_txs, lambda tx: tx['hash'])
    hashes: set[str] = (
      set(grouped_native)
      | set(grouped_token_txs)
      | set(grouped_nft_txs)
      | set(grouped_internal_txs)
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

  def parse_internal_txs(
    self, internal_txs: list[InternalTransaction]
  ) -> list[EvmTx.NativeTransfer]:
    """Parse internal Etherscan rows into SDK native transfers."""
    transfers: list[EvmTx.NativeTransfer] = []
    for tx in internal_txs:
      transfer = self.parse_native_transfer(
        from_=tx['from'],
        to=tx['to'],
        wei=tx['value'],
        internal=True,
      )
      if transfer is not None:
        transfers.append(transfer)
    return transfers

  def parse_token_tx(self, token_tx: TokenTransaction) -> EvmTx.ERC20Transfer | None:
    """Parse an ERC-20 Etherscan row into an SDK ERC-20 transfer."""
    value = token_value(token_tx)
    to, from_ = token_tx['to'], token_tx['from']
    if same_address(to, self.address):
      amount, counterparty = value, from_
    elif same_address(from_, self.address):
      amount, counterparty = -value, to
    else:
      return None
    return EvmTx.ERC20Transfer(
      asset=Web3.to_checksum_address(token_tx['contractAddress']),
      change=amount,
      counterparty=counterparty,
    )

  def parse_token_txs(
    self, token_txs: list[TokenTransaction]
  ) -> list[EvmTx.ERC20Transfer]:
    """Parse ERC-20 Etherscan rows into SDK ERC-20 transfers."""
    return [
      transfer for tx in token_txs if (transfer := self.parse_token_tx(tx)) is not None
    ]

  def parse_nft_tx(self, nft_tx: NftTransaction) -> EvmTx.NftTransfer | None:
    """Parse an ERC-721 Etherscan row into an SDK NFT transfer."""
    to, from_ = nft_tx['to'], nft_tx['from']
    if same_address(to, self.address):
      sign, counterparty = 1, from_
    elif same_address(from_, self.address):
      sign, counterparty = -1, to
    else:
      return None
    return EvmTx.NftTransfer(
      contract_address=nft_tx['contractAddress'],
      token_id=str(nft_tx['tokenID']),
      change=Decimal(sign),
      counterparty=counterparty,
    )

  def parse_nft_txs(self, nft_txs: list[NftTransaction]) -> list[EvmTx.NftTransfer]:
    """Parse ERC-721 Etherscan rows into SDK NFT transfers."""
    return [
      transfer for tx in nft_txs if (transfer := self.parse_nft_tx(tx)) is not None
    ]

  async def parse_tx(
    self,
    hash: str,
    *,
    native: list[NativeTransaction],
    token: list[TokenTransaction],
    nft: list[NftTransaction],
    internal: list[InternalTransaction],
  ) -> EvmTx:
    """Map every feed row sharing one hash, plus its receipt, onto a single `EvmTx`.

    A reverted transaction moved nothing, so its transfers are dropped, while its fee
    and its logs are kept.
    """
    if len(native) > 1:
      raise ValueError('Multiple native transactions')
    rows: list[FeedRow] = [*native, *token, *nft, *internal]
    time = rows[0]['timeStamp']
    tx, receipt = await self.get_tx_data(hash)

    transfers: list[EvmTx.Transfer] = []
    if receipt['status'] != 0:
      transfers = (
        self.parse_native_transfers(tx)
        + self.parse_token_txs(token)
        + self.parse_nft_txs(nft)
        + self.parse_internal_txs(internal)
      )

    return EvmTx(
      id=hash,
      tx_id=hash,
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
        return await self.parse_tx(
          hash, native=native, token=token, nft=nft, internal=internal
        )

    coros = [
      parse_limited(hash, native, token, nft, internal)
      for hash, (native, token, nft, internal) in transactions.items()
    ]
    async with managed_tasks(coros) as tasks:
      for task in asyncio.as_completed(tasks):
        tx = await task
        yield HistoryRecord(
          observations=[tx],
          provenance={'source': 'api', 'service': 'etherscan', 'id': id},
        )
