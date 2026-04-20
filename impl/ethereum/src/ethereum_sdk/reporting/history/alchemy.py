from typing_extensions import AsyncIterable, Callable, Awaitable, TypeVar
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import asyncio

from web3.types import TxReceipt, TxData, BlockIdentifier, _Hash32
from web3 import Web3

from ethereum_sdk.core import alchemy, rpc, wei2eth, same_address
from alchemy.api.transfers import Transfers, Transfer, Params
from ethereum import NodeRpc

from trading_sdk.core import SDK
from trading_sdk.reporting.history import History, EvmTx

T = TypeVar('T')

def tx_fee(tx: TxReceipt) -> Decimal:
  """Transaction fee [ETH]"""
  used = Decimal(tx['gasUsed']) # gas
  price = Decimal(tx['effectiveGasPrice']) # wei/gas
  return wei2eth(price*used)

def parse_execution(tx: TxData) -> EvmTx.Execution | None:
  if (input := tx.get('input')):
    assert 'to' in tx
    return EvmTx.Execution(
      contract_address=Web3.to_checksum_address(tx['to']),
      input=input.to_0x_hex(),
    )

def fmt_hex(number: int) -> str:
  return f'0x{number:x}'

@dataclass
class AlchemyHistory(alchemy.Mixin, rpc.Mixin, History):
  address: str
  include_internal_transfers: bool = field(kw_only=True)
  batch_size: int = field(default=32, kw_only=True)
  block_timestamps_cache: dict[BlockIdentifier, asyncio.Future[datetime]] = field(default_factory=dict, kw_only=True)

  @classmethod
  def alchemy_new(
    cls, address: str, *, alchemy_url: str, rpc_url: str, api_key: str | None = None, validate: bool = True,
    include_internal_transfers: bool = False,
    batch_size: int = 32, poa_middleware: bool = False,
  ):
    transfers = Transfers.new(alchemy_url, api_key=api_key, validate=validate)
    node = NodeRpc.at(rpc_url, poa_middleware=poa_middleware)
    return cls(
      address=address,
      node=node,
      alchemy_transfers=transfers,
      include_internal_transfers=include_internal_transfers,
      batch_size=batch_size,
    )

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx_receipt(self, hash: _Hash32 | str) -> TxReceipt:
    return await self.w3.eth.get_transaction_receipt(hash) # type: ignore

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx(self, hash: _Hash32 | str) -> TxData:
    return await self.w3.eth.get_transaction(hash) # type: ignore

  @SDK.method
  @rpc.wrap_exceptions
  async def get_block_timestamp(self, number: BlockIdentifier) -> datetime:
    block = await self.w3.eth.get_block(number)
    assert 'timestamp' in block
    return datetime.fromtimestamp(block['timestamp']).astimezone()

  async def get_block_timestamp_cached(self, number: BlockIdentifier) -> datetime:
    if number in self.block_timestamps_cache:
      self.block_timestamps_cache[number] = asyncio.create_task(self.get_block_timestamp(number))
    return await self.block_timestamps_cache[number]

  @SDK.method
  @alchemy.wrap_exceptions
  async def call_alchemy(self, fn: Callable[[], Awaitable[T]]) -> T:
    return await fn()

  @SDK.method
  async def get_transfers(self, *, incoming: bool) -> list[Transfer]:
    out: list[Transfer] = []
    params: Params = {
      'category': ['external', 'erc20', 'erc721', 'erc1155', 'specialnft'],
      'excludeZeroValue': False,
    }
    if self.include_internal_transfers:
      params['category'].append('internal')
    if incoming:
      params['toAddress'] = self.address
    else:
      params['fromAddress'] = self.address

    paging = self.alchemy_transfers.transfers_paged(params)
    state = paging.init
    while state is not None:
      chunk, state = await self.call_alchemy(lambda: paging.next(state))
      out.extend(chunk)
    return out

  async def get_all_transfers(self) -> list[Transfer]:
    out_transfers, in_transfers = await asyncio.gather(
      self.get_transfers(incoming=False),
      self.get_transfers(incoming=True),
    )
    return sorted(in_transfers + out_transfers, key=lambda t: t['blockNum'])

  def parse_fee(self, tx: TxData, receipt: TxReceipt) -> Decimal | None:
    if (from_addr := tx.get('from')) and same_address(from_addr, self.address):
      assert 'hash' in tx
      return tx_fee(receipt)

  def parse_transfer(self, transfer: Transfer) -> EvmTx.Transfer | None:
    if (
      not (value := transfer.get('value'))
      or (to := transfer.get('to')) is None
    ):
      return None

    if same_address(to, self.address):
      direction = 'in'
      counterparty = transfer['from']
    elif same_address(transfer['from'], self.address):
      direction = 'out'
      counterparty = to
    else:
      return None

    if transfer['category'] == 'erc20' and (address := transfer['rawContract'].get('address')):
      return EvmTx.ERC20Transfer(
        contract_address=Web3.to_checksum_address(address),
        value=Decimal(value),
        direction=direction,
        counterparty=counterparty,
      )
    elif transfer['category'] in ('external', 'internal') and value:
      return EvmTx.NativeTransfer(
        value=Decimal(value),
        direction=direction,
        counterparty=counterparty,
        internal=transfer['category'] == 'internal',
      )

  async def parse_tx(self, hash: str, transfers: list[Transfer]) -> EvmTx | None:
    tx, receipt = await asyncio.gather(
      self.get_tx(hash),
      self.get_tx_receipt(hash),
    )
    if receipt['status'] != 1:
      return None
    assert 'blockNumber' in tx
    time = await self.get_block_timestamp(tx['blockNumber'])
    fee = self.parse_fee(tx, receipt)
    return EvmTx(
      id=hash,
      time=time,
      raw={'transfers': transfers},
      source='alchemy',
      hash=hash,
      fee=fee,
      execution=parse_execution(tx),
      transfers=[
        transfer for t in transfers
        if (transfer := self.parse_transfer(t)) is not None
      ],
    )

  @SDK.method
  async def history(self, start: datetime, end: datetime) -> AsyncIterable[History.History]:
    start = start.astimezone()
    end = end.astimezone()
    transfers = await self.get_all_transfers()
    tx_groups = defaultdict[str, list[Transfer]](list)
    for t in transfers:
      tx_groups[t['hash']].append(t)

    sem = asyncio.Semaphore(self.batch_size)
    async def parse_limited(hash: str, transfers: list[Transfer]) -> EvmTx | None:
      async with sem:
        return await self.parse_tx(hash, transfers)

    tasks = [
      parse_limited(hash, transfers)
      for hash, transfers in tx_groups.items()
    ]
    for task in asyncio.as_completed(tasks):
      event = await task
      if event is not None and start <= event.time <= end:
        yield History.History(events=[event], flows=event.flows)

