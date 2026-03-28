from typing_extensions import AsyncIterable, Sequence, TypeVar, Callable, Awaitable, Literal
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import asyncio

from web3 import Web3

from trading_sdk.core import SDK
from trading_sdk.reporting.history import Flow, History, EvmTx

from ethereum_sdk.core import EtherscanMixin, wrap_exceptions
from etherscan.core import tx_value, tx_fee
from etherscan.api.account.transactions import Transaction as NativeTransaction
from etherscan.api.account.token_transactions import TokenTransaction, token_value
from etherscan.api.account.internal_transactions import InternalTransaction

T = TypeVar('T')


def parse_native_transaction(tx: NativeTransaction, *, address: str) -> EvmTx:
  if (method := tx['methodId']) != '0x':
    execution = EvmTx.Execution(
      input=tx['input'],
      method_id=method,
      method_name=tx['functionName'] or None,
    )
  else:
    execution = None

  assert Web3.is_checksum_address(address), f'{address} is not a checksum address'
  from_address = Web3.to_checksum_address(tx['from'])
  to_address = Web3.to_checksum_address(tx['to'])

  if from_address == address:
    value = -tx_value(tx)
    fee = tx_fee(tx)
  elif to_address == address:
    value = tx_value(tx)
    fee = None
  else:
    value = None
    fee = None

  return EvmTx(
    time=datetime.fromtimestamp(int(tx['timeStamp'])),
    hash=tx['hash'],
    value=value,
    fee=fee,
    execution=execution,
    raw=tx,
    source='etherscan:native_transactions',
  )


def parse_token_transaction(tx: TokenTransaction, *, address: str) -> Flow:
  assert Web3.is_checksum_address(address), f'{address} is not a checksum address'
  src_address = Web3.to_checksum_address(tx['from'])
  dst_address = Web3.to_checksum_address(tx['to'])
  assert address in (src_address, dst_address), f'{address} is not in the transaction {src_address} or {dst_address}'
  sign = 1 if dst_address == address else -1
  return Flow(
    time=datetime.fromtimestamp(int(tx['timeStamp'])),
    event_id=tx['hash'],
    asset=Web3.to_checksum_address(tx['contractAddress']),
    change=sign * token_value(tx),
    source='etherscan:token_transactions',
    raw=tx,
  )


def parse_internal_transaction(tx: InternalTransaction, *, address: str) -> Flow:
  assert Web3.is_checksum_address(address), f'{address} is not a checksum address'
  src_address = Web3.to_checksum_address(tx['from'])
  dst_address = Web3.to_checksum_address(tx['to'])
  assert address in (src_address, dst_address), f'{address} is not in the transaction {src_address} or {dst_address}'
  sign = 1 if dst_address == address else -1
  assert tx['contractAddress'] == '', 'Expected internal transactions to be ETH-only'
  return Flow(
    time=datetime.fromtimestamp(int(tx['timeStamp'])),
    event_id=tx['hash'],
    asset='ETH',
    change=sign * tx_value(tx),
    source='etherscan:internal_transactions',
    raw=tx,
  )


class AutoDetect:
  ...


AUTO_DETECT = AutoDetect()
Tx = TypeVar('Tx', Flow, EvmTx)


@dataclass
class EtherscanHistory(EtherscanMixin, History):
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @SDK.method
  @wrap_exceptions
  async def get_block_by_time(self, time: datetime, closest: Literal['before', 'after'] = 'before') -> int:
    return await self.etherscan.block_by_time(time, self.chain_id, closest=closest)

  @SDK.method
  async def native_transactions(self, start_block: int, end_block: int) -> AsyncIterable[Sequence[EvmTx]]:
    paging = self.etherscan.transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    while state is not None:
      chunk, state = await self.call(lambda: paging.next(state))
      yield [parse_native_transaction(tx, address=self.address) for tx in chunk]

  @SDK.method
  async def token_transactions(self, start_block: int, end_block: int) -> AsyncIterable[Sequence[Flow]]:
    paging = self.etherscan.token_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    while state is not None:
      chunk, state = await self.call(lambda: paging.next(state))
      yield [parse_token_transaction(tx, address=self.address) for tx in chunk]

  @SDK.method
  async def internal_transactions(self, start_block: int, end_block: int) -> AsyncIterable[Sequence[Flow]]:
    paging = self.etherscan.internal_transactions_paged(
      self.address,
      self.chain_id,
      start_block=start_block,
      end_block=end_block,
    )
    state = paging.init
    while state is not None:
      chunk, state = await self.call(lambda: paging.next(state))
      yield [parse_internal_transaction(tx, address=self.address) for tx in chunk]

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo  # type: ignore
    return self.tz

  def add_tz(self, tx: Tx) -> Tx:
    return replace(tx, time=tx.time.replace(tzinfo=self.timezone))

  @SDK.method
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    start_block, end_block = await asyncio.gather(
      self.get_block_by_time(start, closest='after'),
      self.get_block_by_time(end, closest='before'),
    )

    async for chunk in self.native_transactions(start_block=start_block, end_block=end_block):
      events = [self.add_tz(tx) for tx in chunk]
      yield History.History(events=events)

    async for chunk in self.token_transactions(start_block=start_block, end_block=end_block):
      flows = [self.add_tz(tx) for tx in chunk]
      yield History.History(flows=flows)

    async for chunk in self.internal_transactions(start_block=start_block, end_block=end_block):
      flows = [self.add_tz(tx) for tx in chunk]
      yield History.History(flows=flows)
