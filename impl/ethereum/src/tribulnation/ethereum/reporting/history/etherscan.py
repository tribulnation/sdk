from typing_extensions import Literal, Awaitable, Callable, TypeVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio

from web3 import Web3
from etherscan import Etherscan
from etherscan.api.account.transactions import Transaction as NativeTransaction
from etherscan.api.account.token_transactions import TokenTransaction, token_value
from etherscan.api.account.internal_transactions import InternalTransaction

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import History, Record, EvmTx, source_id
from tribulnation.ethereum.core import etherscan as etherscan_core, group_by, same_address
from tribulnation.ethereum.reporting.util import AutoDetect, AUTO_DETECT, cached_etherscan
from .mixin import HistoryMixin

T = TypeVar('T')

@dataclass(frozen=True, kw_only=True)
class EtherscanHistory(HistoryMixin, History):
  """Etherscan-backed EVM history source."""
  etherscan: Etherscan = field(default_factory=cached_etherscan)
  chain_id: int
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""
  batch_size: int = 4

  async def __aenter__(self):
    await asyncio.gather(
      super().__aenter__(),
      self.etherscan.__aenter__(),
    )
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    await asyncio.gather(
      super().__aexit__(exc_type, exc_value, traceback),
      self.etherscan.__aexit__(exc_type, exc_value, traceback),
    )

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

    return await asyncio.gather(
      get_start(),
      get_end(),
    )

  async def fetch_all_transactions(self, start: datetime | None = None, end: datetime | None = None):
    """Fetch all transactions for the given time range."""
    start_block, end_block = await self.fetch_limits(start, end)
    all_native, all_token_txs, all_internal_txs = await asyncio.gather(
      self.native_transactions(start_block, end_block),
      self.token_transactions(start_block, end_block),
      self.internal_transactions(start_block, end_block),
    )
    grouped_native = group_by(all_native, lambda tx: tx['hash'])
    grouped_token_txs = group_by(all_token_txs, lambda tx: tx['hash'])
    grouped_internal_txs = group_by(all_internal_txs, lambda tx: tx['hash'])
    hashes = set(grouped_native) | set(grouped_token_txs) | set(grouped_internal_txs)
    return {
      hash: (
        grouped_native.get(hash, []),
        grouped_token_txs.get(hash, []),
        grouped_internal_txs.get(hash, []),
      )
      for hash in hashes
    }

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

  async def parse_tx(
    self, hash: str, *,
    native: list[NativeTransaction],
    token: list[TokenTransaction],
    internal: list[InternalTransaction]
  ) -> EvmTx | None:
    if len(native) > 1:
      raise ValueError('Multiple native transactions')
    all_txs = native + token + internal
    any_tx = all_txs[0]
    time = self.add_tz(any_tx['timeStamp'])
    tx, receipt = await self.get_tx_data(hash)

    if receipt['status'] == 0:
      transfers = []
    else:
      transfers: list[EvmTx.Transfer] = (
        self.parse_native_transfers(tx) # type: ignore
        + self.parse_token_txs(token)
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
      internal: list[InternalTransaction],
    ):
      async with semaphore:
        return await self.parse_tx(hash, native=native, token=token, internal=internal)

    tasks = [
      parse_limited(hash, native, token, internal)
      for hash, (native, token, internal) in transactions.items()
    ]
    for task in asyncio.as_completed(tasks):
      tx = await task
      if tx is not None:
        yield Record(observations=[tx], provenance={'source': 'api', 'service': 'etherscan', 'id': id})
