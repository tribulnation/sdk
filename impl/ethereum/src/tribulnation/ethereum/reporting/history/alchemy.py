"""Alchemy-backed EVM reporting history."""

from typing_extensions import AsyncIterable, Callable, Awaitable, TypeVar, Any
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import asyncio

from web3.types import TxReceipt, TxData, BlockIdentifier, _Hash32
from web3 import Web3

from tribulnation.ethereum.core import alchemy, rpc, wei2eth, same_address
from alchemy.api.transfers import Transfers
from alchemy.api.transfers.get_asset_transfers import AssetTransfersBaseParams, Transfer
from ethereum import NodeRpc

from tribulnation.sdk.core import SDK
from tribulnation.sdk.reporting import Fee, EvmTx, Record

T = TypeVar('T')

def wei_field(value: Any) -> Decimal:
  """Return a wei-valued receipt field as a decimal integer."""
  if value is None:
    return Decimal('0')
  if isinstance(value, str) and value.startswith('0x'):
    return Decimal(int(value, 16))
  return Decimal(value)

def tx_fee(tx: TxReceipt) -> Decimal:
  """Return the full transaction fee in native units."""
  used = wei_field(tx['gasUsed'])
  price = wei_field(tx['effectiveGasPrice'])
  l1_fee = wei_field(tx.get('l1Fee'))
  operator_fee = wei_field(tx.get('operatorFee'))
  return wei2eth(used * price + l1_fee + operator_fee)

def parse_execution(tx: TxData) -> EvmTx.Execution | None:
  """Parse contract execution metadata from a raw transaction."""
  if (input := tx.get('input')):
    assert 'to' in tx
    return EvmTx.Execution(
      contract_address=Web3.to_checksum_address(tx['to']),
      input=input.to_0x_hex(),
    )

def fmt_hex(number: int) -> str:
  """Format a block number as an Alchemy hex quantity."""
  return f'0x{number:x}'

class AlchemyHistory:
  """Alchemy-backed EVM history source."""
  address: str
  node: NodeRpc | None
  alchemy_transfers: Transfers | None
  include_internal_transfers: bool = False
  batch_size: int = 32
  block_timestamps_cache: dict[BlockIdentifier, asyncio.Future[datetime]]

  @property
  def w3(self):
    """Return the configured Web3 client."""
    node = self.require_node()
    return node.w3

  def require_node(self) -> NodeRpc:
    """Return the configured node client."""
    if self.node is None:
      raise ValueError('Alchemy history requires an RPC client.')
    return self.node

  def require_alchemy_transfers(self) -> Transfers:
    """Return the configured Alchemy transfers client."""
    if self.alchemy_transfers is None:
      raise ValueError('Alchemy history requires an Alchemy transfers provider.')
    return self.alchemy_transfers

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx_receipt(self, hash: _Hash32 | str) -> TxReceipt:
    """Fetch a transaction receipt from the configured node."""
    return await self.w3.eth.get_transaction_receipt(hash) # type: ignore

  @SDK.method
  @rpc.wrap_exceptions
  async def get_tx(self, hash: _Hash32 | str) -> TxData:
    """Fetch a transaction by hash from the configured node."""
    return await self.w3.eth.get_transaction(hash) # type: ignore

  @SDK.method
  @rpc.wrap_exceptions
  async def get_block_timestamp(self, number: BlockIdentifier) -> datetime:
    """Fetch a block timestamp from the configured node."""
    block = await self.w3.eth.get_block(number)
    assert 'timestamp' in block
    return datetime.fromtimestamp(block['timestamp']).astimezone()

  async def get_block_timestamp_cached(self, number: BlockIdentifier) -> datetime:
    """Fetch a block timestamp with per-report request coalescing."""
    if number not in self.block_timestamps_cache:
      self.block_timestamps_cache[number] = asyncio.create_task(self.get_block_timestamp(number))
    return await self.block_timestamps_cache[number]

  @SDK.method
  @alchemy.wrap_exceptions
  async def call_alchemy(self, fn: Callable[[], Awaitable[T]]) -> T:
    """Call Alchemy under the SDK exception wrapper."""
    return await fn()

  @SDK.method
  async def get_transfers(self, *, incoming: bool) -> list[Transfer]:
    """Fetch one direction of Alchemy asset transfers for this wallet."""
    out: list[Transfer] = []
    params: AssetTransfersBaseParams = {
      'category': ['external', 'erc20', 'erc721', 'erc1155', 'specialnft'],
      'excludeZeroValue': False,
    }
    if self.include_internal_transfers:
      params['category'].append('internal')
    if incoming:
      params['toAddress'] = self.address
    else:
      params['fromAddress'] = self.address

    paging = self.require_alchemy_transfers().transfers_paged(params)
    state = paging.init
    while state is not None:
      chunk, state = await self.call_alchemy(lambda: paging.next(state)) # type: ignore
      out.extend(chunk)
    return out

  async def get_all_transfers(self) -> list[Transfer]:
    """Fetch incoming and outgoing Alchemy transfers."""
    out_transfers, in_transfers = await asyncio.gather(
      self.get_transfers(incoming=False),
      self.get_transfers(incoming=True),
    )
    return sorted(in_transfers + out_transfers, key=lambda t: t['blockNum'])

  def alchemy_parse_fee(self, tx: TxData, receipt: TxReceipt) -> Fee | None:
    """Parse an EVM gas fee paid by this wallet."""
    if (from_addr := tx.get('from')) and same_address(from_addr, self.address):
      assert 'hash' in tx
      return Fee(asset='native', amount=tx_fee(receipt))

  def alchemy_parse_transfer(self, transfer: Transfer) -> EvmTx.Transfer | None:
    """Parse an Alchemy transfer row into an SDK EVM transfer."""
    if (
      not (value := transfer.get('value'))
      or (to := transfer.get('to')) is None
    ):
      return None

    if same_address(to, self.address):
      amount = Decimal(str(value))
      counterparty = transfer['from']
    elif same_address(transfer['from'], self.address):
      amount = -Decimal(str(value))
      counterparty = to
    else:
      return None

    if transfer['category'] == 'erc20' and (address := transfer['rawContract'].get('address')):
      return EvmTx.ERC20Transfer(
        asset=Web3.to_checksum_address(address),
        change=amount,
        counterparty=counterparty,
      )
    elif transfer['category'] in ('external', 'internal') and value:
      return EvmTx.NativeTransfer(
        change=amount,
        counterparty=counterparty,
        internal=transfer['category'] == 'internal',
      )

  async def alchemy_parse_tx(self, hash: str, transfers: list[Transfer]) -> EvmTx | None:
    """Build an SDK EVM transaction from grouped Alchemy transfer rows."""
    tx, receipt = await asyncio.gather(
      self.get_tx(hash),
      self.get_tx_receipt(hash),
    )
    if receipt['status'] != 1:
      return None
    assert 'blockNumber' in tx
    time = await self.get_block_timestamp(tx['blockNumber'])
    fee = self.alchemy_parse_fee(tx, receipt)
    return EvmTx(
      id=hash,
      tx_id=hash,
      time=time,
      fee=fee,
      execution=parse_execution(tx),
      transfers=[
        transfer for t in transfers
        if (transfer := self.alchemy_parse_transfer(t)) is not None
      ],
    )

  @SDK.method
  async def alchemy_history(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterable[Record]:
    """Fetch EVM history from Alchemy asset transfers."""
    start = start and start.astimezone()
    end = end and end.astimezone()
    transfers = await self.get_all_transfers()
    tx_groups = defaultdict[str, list[Transfer]](list)
    for t in transfers:
      tx_groups[t['hash']].append(t)

    sem = asyncio.Semaphore(self.batch_size)
    async def parse_limited(hash: str, transfers: list[Transfer]) -> EvmTx | None:
      """Parse a transaction while respecting the configured concurrency limit."""
      async with sem:
        return await self.alchemy_parse_tx(hash, transfers)

    tasks = [
      parse_limited(hash, transfers)
      for hash, transfers in tx_groups.items()
    ]

    def filter_event(event: EvmTx) -> bool:
      """Return whether an event is inside the requested time window."""
      if start is not None and event.time is not None and event.time < start:
        return False
      if end is not None and event.time is not None and event.time > end:
        return False
      return True

    for task in asyncio.as_completed(tasks):
      event = await task
      if event is not None and filter_event(event):
        yield Record(observations=[event], provenance={'source': 'api', 'service': 'alchemy'})
