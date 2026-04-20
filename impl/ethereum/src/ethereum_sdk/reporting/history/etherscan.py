from typing_extensions import Literal, AsyncIterable, TypeVar, Awaitable, Callable
from dataclasses import dataclass
from datetime import timezone, datetime
import asyncio

from web3 import Web3
from etherscan.core import tx_value, tx_fee
from etherscan.api.account.transactions import Transaction as NativeTransaction
from etherscan.api.account.token_transactions import TokenTransaction, token_value
from etherscan.api.account.internal_transactions import InternalTransaction

from trading_sdk.core import SDK
from trading_sdk.reporting.history import History, EvmTx
from ethereum_sdk.core import etherscan, group_by, same_address

T = TypeVar('T')

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

@dataclass
class EtherscanHistory(etherscan.Mixin, History):
  address: str
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @SDK.method
  @etherscan.wrap_exceptions
  async def get_block_by_time(self, time: datetime, closest: Literal['before', 'after'] = 'before') -> int:
    return await self.etherscan.blocks.block_by_time(time, self.chain_id, closest=closest)

  @SDK.method
  @etherscan.wrap_exceptions
  async def call_etherscan(self, fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()

  @SDK.method
  async def native_transactions(self, start_block: int, end_block: int):
    paging = self.etherscan.account.transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[NativeTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state))
      out.extend(chunk)
    return out

  @SDK.method
  async def token_transactions(self, start_block: int, end_block: int):
    paging = self.etherscan.account.token_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[TokenTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state))
      out.extend(chunk)
    return out

  @SDK.method
  async def internal_transactions(self, start_block: int, end_block: int):
    paging = self.etherscan.account.internal_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    out: list[InternalTransaction] = []
    while state is not None:
      chunk, state = await self.call_etherscan(lambda: paging.next(state))
      out.extend(chunk)
    return out

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo  # type: ignore
    return self.tz

  def parse_execution(self, tx: NativeTransaction) -> EvmTx.Execution | None:
    if (method := tx['methodId']) != '0x':
      return EvmTx.Execution(
        contract_address=tx['contractAddress'],
        input=tx['input'],
        method_name=tx['functionName'] or None,
      )

  def parse_native_transfer(self, tx: NativeTransaction | InternalTransaction, *, internal: bool) -> EvmTx.NativeTransfer | None:
    if (value := tx_value(tx)) > 0:
      if same_address(tx['to'], self.address):
        direction = 'in'
        counterparty = tx['from']
      elif same_address(tx['from'], self.address):
        direction = 'out'
        counterparty = tx['to']
      else:
        return None
      return EvmTx.NativeTransfer(
        direction=direction,
        counterparty=counterparty,
        value=value,
        internal=internal,
      )


  def parse_native_txs(self, native_txs: list[NativeTransaction]) -> list[EvmTx.NativeTransfer]:
    return [
      transfer for tx in native_txs
      if (transfer := self.parse_native_transfer(tx, internal=False)) is not None
    ]

  def parse_internal_txs(self, internal_txs: list[InternalTransaction]) -> list[EvmTx.NativeTransfer]:
    return [
      transfer for tx in internal_txs
      if (transfer := self.parse_native_transfer(tx, internal=True)) is not None
    ]

  def parse_token_tx(self, token_tx: TokenTransaction) -> EvmTx.ERC20Transfer | None:
    if same_address(token_tx['to'], self.address):
      direction = 'in'
      counterparty = token_tx['from']
    elif same_address(token_tx['from'], self.address):
      direction = 'out'
      counterparty = token_tx['to']
    else:
      return None
    return EvmTx.ERC20Transfer(
      contract_address=Web3.to_checksum_address(token_tx['contractAddress']),
      value=token_value(token_tx),
      direction=direction,
      counterparty=counterparty,
    )

  def parse_token_txs(self, token_txs: list[TokenTransaction]) -> list[EvmTx.ERC20Transfer]:
    return [
      transfer for tx in token_txs
      if (transfer := self.parse_token_tx(tx)) is not None
    ]

  def parse_tx(
    self, hash: str, *,
    native_txs: list[NativeTransaction],
    token_txs: list[TokenTransaction],
    internal_txs: list[InternalTransaction],
  ) -> EvmTx | None:
    if len(native_txs) > 1:
      raise ValueError('Multiple native transactions')
    all_txs = native_txs + token_txs + internal_txs
    any_tx = all_txs[0]
    native_tx = native_txs[0] if native_txs else None

    if native_tx and native_tx['isError'] != '0':
      return

    transfers = self.parse_native_txs(native_txs) + self.parse_token_txs(token_txs) + self.parse_internal_txs(internal_txs)

    return EvmTx(
      id=hash, hash=hash,
      time=any_tx['timeStamp'],
      fee=native_tx and tx_fee(native_tx),
      transfers=transfers,
      raw={
        'native_txs': native_txs,
        'token_txs': token_txs,
        'internal_txs': internal_txs,
      },
      source='etherscan',
    )


  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    start_block, end_block = await asyncio.gather(
      self.get_block_by_time(start, 'before'),
      self.get_block_by_time(end, 'after'),
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
    transactions: list[EvmTx] = []
    for hash in hashes:
      native_txs = grouped_native_txs.get(hash, [])
      token_txs = grouped_token_txs.get(hash, [])
      internal_txs = grouped_internal_txs.get(hash, [])
      tx = self.parse_tx(hash, native_txs=native_txs, token_txs=token_txs, internal_txs=internal_txs)
      if tx is not None:
        transactions.append(tx)
    for tx in sorted(transactions, key=lambda tx: tx.time):
      yield History.History(events=[tx], flows=tx.flows)
