from typing_extensions import AsyncIterable, Sequence, TypeVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from web3 import Web3

from trading_sdk.reporting.history import Flow, History as _History, EthereumTx

from ethereum_sdk.core import EtherscanMixin
from ethereum.etherscan import tx_value, tx_fee, token_value
from ethereum.etherscan.transactions import Transaction as NativeTransaction
from ethereum.etherscan.token_transactions import TokenTransaction
from ethereum.etherscan.internal_transactions import InternalTransaction

def parse_native_transaction(tx: NativeTransaction, *, address: str) -> EthereumTx:
  if (method := tx['methodId']) != '0x':
    execution = EthereumTx.Execution(
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

  return EthereumTx(
    time=datetime.fromtimestamp(int(tx['timeStamp'])),
    hash=tx['hash'], value=value, fee=fee,
    execution=execution, raw=tx, source='etherscan:native_transactions',
  )


async def native_transactions(
  self: EtherscanMixin, *, start: datetime, end: datetime
) -> AsyncIterable[Sequence[EthereumTx]]:
  kwargs = {}
  if start is not None:
    kwargs['start_block'] = await self.etherscan.block_by_time(start, self.chain_id, closest='after')
  if end is not None:
    end = min(end, datetime.now())
    kwargs['end_block'] = await self.etherscan.block_by_time(end, self.chain_id, closest='before')
  async for chunk in self.etherscan.transactions_paged(self.address, self.chain_id, **kwargs):
    yield [parse_native_transaction(tx, address=self.address) for tx in chunk]


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

async def token_transactions(
  self: EtherscanMixin, *, start: datetime, end: datetime,
) -> AsyncIterable[Sequence[Flow]]:
  kwargs = {}
  if start is not None:
    kwargs['start_block'] = await self.etherscan.block_by_time(start, self.chain_id, closest='after')
  if end is not None:
    end = min(end, datetime.now())
    kwargs['end_block'] = await self.etherscan.block_by_time(end, self.chain_id, closest='before')
  async for chunk in self.etherscan.token_transactions_paged(self.address, self.chain_id, **kwargs):
    yield [parse_token_transaction(tx, address=self.address) for tx in chunk]


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

async def internal_transactions(
  self: EtherscanMixin, *, start: datetime, end: datetime,
) -> AsyncIterable[Sequence[Flow]]:
  kwargs = {}
  if start is not None:
    kwargs['start_block'] = await self.etherscan.block_by_time(start, self.chain_id, closest='after')
  if end is not None:
    end = min(end, datetime.now())
    kwargs['end_block'] = await self.etherscan.block_by_time(end, self.chain_id, closest='before')
  async for chunk in self.etherscan.internal_transactions_paged(self.address, self.chain_id, **kwargs):
    yield [parse_internal_transaction(tx, address=self.address) for tx in chunk]

class AutoDetect:
  ...

AUTO_DETECT = AutoDetect()

Tx = TypeVar('Tx', Flow, EthereumTx)

@dataclass
class History(EtherscanMixin, _History):
  tz: timezone | AutoDetect = AUTO_DETECT
  """Timezone of the API times (defaults to the local timezone)."""

  @property
  def timezone(self) -> timezone:
    if isinstance(self.tz, AutoDetect):
      return datetime.now().astimezone().tzinfo # type: ignore
    else:
      return self.tz

  def add_tz(self, tx: Tx) -> Tx:
    return replace(tx, time=tx.time.replace(tzinfo=self.timezone))

  async def history(self, start: datetime, end: datetime) -> AsyncIterable[_History.History]:
    
    async for chunk in native_transactions(self, start=start, end=end):
      events = [self.add_tz(tx) for tx in chunk]
      yield _History.History(events=events)
      
    async for chunk in token_transactions(self, start=start, end=end):
      flows = [self.add_tz(tx) for tx in chunk]
      yield _History.History(flows=flows)

    async for chunk in internal_transactions(self, start=start, end=end):
      flows = [self.add_tz(tx) for tx in chunk]
      yield _History.History(flows=flows)