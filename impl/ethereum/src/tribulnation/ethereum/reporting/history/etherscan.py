"""Etherscan-backed EVM reporting history."""

from typing_extensions import Literal, AsyncIterable, TypeVar, Awaitable, Callable
from datetime import timezone, datetime
from dataclasses import dataclass
import asyncio

from web3 import Web3
from etherscan import Etherscan
from etherscan.core import tx_value, tx_fee
from etherscan.api.account.transactions import Transaction as NativeTransaction
from etherscan.api.account.token_transactions import TokenTransaction, token_value
from etherscan.api.account.internal_transactions import InternalTransaction

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Fee, EvmTx, Record
from tribulnation.ethereum.core import etherscan as etherscan_core, group_by, same_address
from ..util import source_id

T = TypeVar('T')

class AutoDetect:
  """Sentinel for automatic local timezone detection."""
  ...

AUTO_DETECT = AutoDetect()

@dataclass(frozen=True)
class EtherscanHistory(SDK):
  """Etherscan-backed EVM history source."""
  address: str
  chain_id: int
  etherscan: Etherscan | None
  block_time_cache: dict[int, datetime]
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  def require_etherscan(self) -> Etherscan:
    """Return the configured Etherscan client."""
    if self.etherscan is None:
      raise ValueError('Etherscan history requires an Etherscan provider.')
    return self.etherscan

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
    return await self.require_etherscan().blocks.block_by_time(time, self.chain_id, closest=closest)

  @SDK.method
  @etherscan_core.wrap_exceptions
  async def call_etherscan(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Etherscan under the SDK exception wrapper."""
    return await fn()

  @SDK.method
  async def native_transactions(self, start_block: int, end_block: int) -> list[NativeTransaction]:
    """Fetch native transactions from Etherscan."""
    paging = self.require_etherscan().account.transactions_paged(
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
    paging = self.require_etherscan().account.token_transactions_paged(
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
    paging = self.require_etherscan().account.internal_transactions_paged(
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

  def etherscan_parse_execution(self, tx: NativeTransaction) -> EvmTx.Execution | None:
    """Parse contract execution metadata from a native transaction."""
    if (method := tx['methodId']) != '0x':
      return EvmTx.Execution(
        contract_address=tx['contractAddress'],
        input=tx['input'],
        method_name=tx['functionName'] or None,
      )

  def etherscan_parse_native_transfer(
    self, tx: NativeTransaction | InternalTransaction, *, internal: bool,
  ) -> EvmTx.NativeTransfer | None:
    """Parse a native transaction row into an SDK native transfer."""
    if (value := tx_value(tx)) > 0:
      if same_address(tx['to'], self.address):
        amount = value
        counterparty = tx['from']
      elif same_address(tx['from'], self.address):
        amount = -value
        counterparty = tx['to']
      else:
        return None
      return EvmTx.NativeTransfer(
        counterparty=counterparty,
        change=amount,
        internal=internal,
      )


  def etherscan_parse_native_txs(self, native_txs: list[NativeTransaction]) -> list[EvmTx.NativeTransfer]:
    """Parse native Etherscan rows into SDK native transfers."""
    return [
      transfer for tx in native_txs
      if (transfer := self.etherscan_parse_native_transfer(tx, internal=False)) is not None
    ]

  def etherscan_parse_internal_txs(self, internal_txs: list[InternalTransaction]) -> list[EvmTx.NativeTransfer]:
    """Parse internal Etherscan rows into SDK native transfers."""
    return [
      transfer for tx in internal_txs
      if (transfer := self.etherscan_parse_native_transfer(tx, internal=True)) is not None
    ]

  def etherscan_parse_token_tx(self, token_tx: TokenTransaction) -> EvmTx.ERC20Transfer | None:
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

  def etherscan_parse_token_txs(self, token_txs: list[TokenTransaction]) -> list[EvmTx.ERC20Transfer]:
    """Parse ERC20 Etherscan rows into SDK ERC20 transfers."""
    return [
      transfer for tx in token_txs
      if (transfer := self.etherscan_parse_token_tx(tx)) is not None
    ]

  def etherscan_parse_fee(self, tx: NativeTransaction) -> Fee | None:
    """Parse an EVM gas fee paid by this wallet."""
    if same_address(tx['from'], self.address):
      return Fee(asset='native', amount=tx_fee(tx))

  def etherscan_parse_tx(
    self, hash: str, *,
    native_txs: list[NativeTransaction],
    token_txs: list[TokenTransaction],
    internal_txs: list[InternalTransaction],
  ) -> EvmTx | None:
    """Build an SDK EVM transaction from grouped Etherscan rows."""
    if len(native_txs) > 1:
      raise ValueError('Multiple native transactions')
    all_txs = native_txs + token_txs + internal_txs
    any_tx = all_txs[0]
    native_tx = native_txs[0] if native_txs else None
    time = self.add_tz(any_tx['timeStamp'])

    if native_tx and native_tx['isError'] != '0':
      fee = self.etherscan_parse_fee(native_tx)
      if fee is None:
        return
      return EvmTx(
        id=hash, tx_id=hash,
        time=time,
        fee=fee,
        execution=self.etherscan_parse_execution(native_tx),
        transfers=[],
      )

    transfers = (
      self.etherscan_parse_native_txs(native_txs)
      + self.etherscan_parse_token_txs(token_txs)
      + self.etherscan_parse_internal_txs(internal_txs)
    )

    return EvmTx(
      id=hash, tx_id=hash,
      time=time,
      fee=native_tx and self.etherscan_parse_fee(native_tx),
      transfers=transfers,
    )


  async def etherscan_history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch EVM history from Etherscan account endpoints."""

    async def get_start():
      """Resolve the first block to request."""
      if start is None:
        return 0
      else:
        return await self.get_block_by_time(start, 'before')

    async def get_end():
      """Resolve the last block to request."""
      if end is None:
        return await self.call_etherscan(lambda: self.require_etherscan().proxy.eth_block_number(chain_id=self.chain_id))
      else:
        return await self.get_block_by_time(end, 'after')

    start_block, end_block = await asyncio.gather(
      get_start(),
      get_end(),
    )

    all_native_txs, all_token_txs, all_internal_txs = await asyncio.gather(
      self.native_transactions(start_block=start_block, end_block=end_block),
      self.token_transactions(start_block=start_block, end_block=end_block),
      self.internal_transactions(start_block=start_block, end_block=end_block),
    )

    grouped_native_txs = group_by(all_native_txs, lambda tx: tx['hash'])
    grouped_token_txs = group_by(all_token_txs, lambda tx: tx['hash'])
    grouped_internal_txs = group_by(all_internal_txs, lambda tx: tx['hash'])

    hashes = list(set(grouped_native_txs) | set(grouped_token_txs) | set(grouped_internal_txs))
    for i, hash in enumerate(hashes):
      native_txs = grouped_native_txs.get(hash, [])
      token_txs = grouped_token_txs.get(hash, [])
      internal_txs = grouped_internal_txs.get(hash, [])
      tx = self.etherscan_parse_tx(hash, native_txs=native_txs, token_txs=token_txs, internal_txs=internal_txs)
      if tx is not None:
        yield Record(observations=[tx], provenance={'source': 'api', 'service': 'etherscan', 'id': source_id('etherscan')})
